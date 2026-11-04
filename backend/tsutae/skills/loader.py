"""SKILL.md（YAML frontmatter ＋自然言語の本文）の読み込みと検査。

- frontmatter はアプリが読む機械用の設定。`RegimenSkill` / `ReportFormatSkill` に一致する
- 本文は Agent SDK の主エージェントが読む指示書。アプリは本文を解釈しない
- 失敗は全て `SkillValidationError`（`code` は短い英字の文字列）。D4 の書き換え結果の
  検査にも使うので、壊れた入力・想定外の入力はすべてここで止める
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from pydantic import ValidationError

from tsutae.config import PATIENT_STRINGS_PATH, get_settings
from tsutae.schemas import (
    REGIMEN_CODE_MAX,
    REGIMEN_CODE_PATTERN,
    Regimen,
    RegimenSkill,
    ReportFormatSkill,
)

SKILL_NAME_PATTERN = r"^(regimen|report-format)-[a-z0-9-]+$"
SKILL_FILE_NAME = "SKILL.md"
DEFAULT_REPORT_SKILL = "report-format-default"
# SKILL.md 全文の上限（文字数）。D4 でエージェントが書いた結果の暴走を止める
MAX_SKILL_CHARS = 100_000

# 評価済みの2つ（必須の Skill・FOLFOX/CAPOX の並び）。レジメンの全体ではない（v1.1。
# 置かれているレジメンは `skills.catalog.list_regimens`）
REGIMEN_SKILL_NAMES: Mapping[str, str] = MappingProxyType(
    {"FOLFOX": "regimen-folfox", "CAPOX": "regimen-capox"}
)
_SKILL_MODELS: tuple[tuple[str, type[RegimenSkill] | type[ReportFormatSkill]], ...] = (
    ("regimen-", RegimenSkill),
    ("report-format-", ReportFormatSkill),
)
_SKILL_NAME_RE = re.compile(SKILL_NAME_PATTERN)
_REGIMEN_CODE_RE = re.compile(REGIMEN_CODE_PATTERN)
_FENCE = "---"
# 固定規則の閾値（℃）として受け付ける範囲。ReportFormatSkill.fever_attention_celsius と同じ
_THRESHOLD_MIN_CELSIUS = 35.0
_THRESHOLD_MAX_CELSIUS = 42.0
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"
_MERGE_TAG = "tag:yaml.org,2002:merge"
_VALUE_TAG = "tag:yaml.org,2002:value"  # キー「=」。SafeLoader は str として読む
# YAML の解析・型変換で出うる例外。`!!int abc` は ValueError、深い入れ子は RecursionError
_YAML_FAILURES: tuple[type[BaseException], ...] = (
    yaml.YAMLError,
    ValueError,
    TypeError,
    RecursionError,
)


class SkillValidationError(ValueError):
    """Skill の検査に失敗した。`code` は DB・API に載せる短い文字列。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


class SkillFormatError(SkillValidationError):
    """frontmatter が無い・閉じていない・YAML の mapping として読めない。"""

    def __init__(self, message: str = "") -> None:
        super().__init__("format", message)


class SkillNotFoundError(SkillValidationError):
    """SKILL.md が置かれていない。"""

    def __init__(self, message: str = "") -> None:
        super().__init__("not_found", message)


# ---------------------------------------------------------------------------
# 名前と置き場所
# ---------------------------------------------------------------------------


def is_valid_skill_name(skill_name: object) -> bool:
    """`SKILL_NAME_PATTERN` に完全一致するか（末尾の改行も許さない）。"""
    return (
        isinstance(skill_name, str) and _SKILL_NAME_RE.fullmatch(skill_name) is not None
    )


def _require_valid_name(skill_name: object) -> str:
    if not is_valid_skill_name(skill_name):
        raise SkillValidationError("invalid_name", "Skill 名の書式が違う")
    return str(skill_name)


def skill_path(skill_name: str, skills_dir: Path | None = None) -> Path:
    """`<skills_dir>/<skill_name>/SKILL.md`。書式に合わない名前は拒否する。"""
    name = _require_valid_name(skill_name)
    base = Path(skills_dir) if skills_dir is not None else get_settings().skills_dir
    path = base / name / SKILL_FILE_NAME
    # 名前の検査で十分だが、シンボリックリンク経由で外へ出ることも防ぐ
    if not path.resolve().is_relative_to(base.resolve()):
        raise SkillValidationError("invalid_name", "skills_dir の外を指している")
    return path


def read_skill_text(skill_name: str, skills_dir: Path | None = None) -> str:
    path = skill_path(skill_name, skills_dir)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SkillNotFoundError(f"{skill_name} が無い") from exc
    except UnicodeDecodeError as exc:
        raise SkillFormatError("UTF-8 として読めない") from exc
    except OSError as exc:
        raise SkillNotFoundError(f"{skill_name} を読めない") from exc


# ---------------------------------------------------------------------------
# YAML の読み方
# ---------------------------------------------------------------------------


class _DuplicateKeyError(yaml.constructor.ConstructorError):
    """同じ mapping に同じキーが2回ある。"""


class _SkillYamlLoader(yaml.SafeLoader):
    """frontmatter 用の SafeLoader。

    - 重複したキーを拒否する。safe_load は黙って後勝ちにするので、D4 でブロックを
      足すと、差分には追加しか出ないのに既存の項目が消える
    - 日付・日時風の値を date / datetime に変えず str のまま残す（下の resolver）
    """

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        if not isinstance(node, yaml.MappingNode):  # 親が ConstructorError を出す
            return super().construct_mapping(node, deep=deep)
        seen: set[Any] = set()
        for key_node, _value_node in node.value:
            if key_node.tag == _MERGE_TAG:  # `<<: *anchor` は YAML の標準どおり
                continue
            key = (
                self.construct_scalar(key_node)
                if key_node.tag == _VALUE_TAG
                else self.construct_object(key_node, deep=True)
            )
            if key in seen:  # ハッシュできないキーは TypeError（呼び出し側で format）
                raise _DuplicateKeyError(
                    None, None, "キーが重複している", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


# 親（yaml.SafeLoader）の dict・list は共有なので、書き換えずに新しい dict を作る
_SkillYamlLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _TIMESTAMP_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


# ---------------------------------------------------------------------------
# 解析と検査
# ---------------------------------------------------------------------------


def _load_yaml(source: str) -> Any:
    try:
        return yaml.load(source, Loader=_SkillYamlLoader)
    except _DuplicateKeyError as exc:
        raise SkillFormatError(
            f"frontmatter のキーが重複している（{exc.problem_mark.line + 2} 行目）"
            if exc.problem_mark is not None
            else "frontmatter のキーが重複している"
        ) from exc
    except _YAML_FAILURES as exc:
        raise SkillFormatError("frontmatter が YAML として読めない") from exc


def parse_skill_md(text: str) -> tuple[dict[str, Any], str]:
    """frontmatter（dict）と本文を返す。壊れていれば `SkillFormatError`。"""
    if not isinstance(text, str):
        raise SkillFormatError("SKILL.md が文字列でない")
    lines = text.removeprefix("\ufeff").replace("\r\n", "\n").split("\n")
    if lines[0].rstrip() != _FENCE:
        raise SkillFormatError("frontmatter が無い")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == _FENCE), None)
    if end is None:
        raise SkillFormatError("frontmatter が閉じていない")
    meta = _load_yaml("\n".join(lines[1:end]))
    if not isinstance(meta, dict):
        raise SkillFormatError("frontmatter が mapping でない")
    return meta, "\n".join(lines[end + 1 :])


def _model_for(
    skill_name: object,
) -> type[RegimenSkill] | type[ReportFormatSkill]:
    if isinstance(skill_name, str):
        for prefix, model in _SKILL_MODELS:
            if skill_name.startswith(prefix):
                return model
    raise SkillValidationError(
        "unknown_kind", "Skill 名は regimen- か report-format- で始める"
    )


def _summarize(exc: ValidationError) -> str:
    """pydantic のエラーを場所と理由だけに縮める（入力値は載せない）。"""
    parts = [
        f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    ]
    return "; ".join(parts)


@lru_cache(maxsize=1)
def _patient_string_keys() -> frozenset[str]:
    strings = json.loads(PATIENT_STRINGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(strings, dict):
        raise RuntimeError("patient_strings.json が mapping でない")
    return frozenset(strings)


def _check_fixed_rules(skill: RegimenSkill) -> None:
    """固定規則が「二度と出ない／常に出る」状態にならないことを確かめる（spec §11）。"""
    answer_types = {q.key: q.answer_type for q in skill.questions}
    for i, rule in enumerate(skill.fixed_rules):
        where = f"fixed_rules.{i}"
        threshold = rule.threshold_celsius
        if not (
            math.isfinite(threshold)
            and _THRESHOLD_MIN_CELSIUS <= threshold <= _THRESHOLD_MAX_CELSIUS
        ):
            raise SkillValidationError(
                "schema",
                f"{where}.threshold_celsius: {_THRESHOLD_MIN_CELSIUS}〜"
                f"{_THRESHOLD_MAX_CELSIUS} の数にする",
            )
        if answer_types.get(rule.question_key) != "temperature":
            raise SkillValidationError(
                "schema", f"{where}.question_key: 体温（temperature）の質問でない"
            )
        if rule.patient_string_key not in _patient_string_keys():
            raise SkillValidationError(
                "schema", f"{where}.patient_string_key: patient_strings.json に無い"
            )


def _check_regimen_skill(name: str, skill: RegimenSkill) -> None:
    """RegimenSkill の型だけでは見ていない、ローダーとパイプラインの前提を確かめる。"""
    # 全ての regimen-* で名前は `regimen-` + 識別名の小文字（v1.1。T91 の検証の指摘）。
    # load_regimen_skill・list_regimens と同じ合否にする（D4 の検査もこちらを通る）
    if regimen_skill_name(skill.regimen) != name:
        raise SkillValidationError(
            "regimen_mismatch", f"{name} の regimen が {skill.regimen} になっている"
        )
    pump = skill.pump_removal_day
    if pump is not None and not 1 <= pump <= skill.cycle_days:
        raise SkillValidationError(
            "schema", "pump_removal_day: 1 以上 cycle_days 以下にする"
        )
    _check_fixed_rules(skill)


def _read_frontmatter(name: str, text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise SkillFormatError("SKILL.md が文字列でない")
    if len(text) > MAX_SKILL_CHARS:
        raise SkillValidationError("too_large", f"{MAX_SKILL_CHARS} 文字を超えている")
    meta, _body = parse_skill_md(text)
    if meta.get("name") != name:
        raise SkillValidationError(
            "name_mismatch", "frontmatter の name と Skill 名が違う"
        )
    return meta


def validate_skill_text(skill_name: str, text: str) -> RegimenSkill | ReportFormatSkill:
    """SKILL.md 全文を検査し、名前の接頭辞に応じた型で返す。"""
    model = _model_for(skill_name)
    name = _require_valid_name(skill_name)
    meta = _read_frontmatter(name, text)
    try:
        # YAML の型をそのまま検査する（"1" を 1 に、true を 1 に直さない）
        skill = model.model_validate(meta, strict=True)
    except ValidationError as exc:
        raise SkillValidationError("schema", _summarize(exc)) from exc
    if isinstance(skill, RegimenSkill):
        _check_regimen_skill(name, skill)
    return skill


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------


def load_skill(
    skill_name: str, skills_dir: Path | None = None
) -> RegimenSkill | ReportFormatSkill:
    return validate_skill_text(skill_name, read_skill_text(skill_name, skills_dir))


def regimen_skill_name(regimen: object) -> str | None:
    """識別名 → Skill 名（FOLFOX → regimen-folfox。D4 で採用した FOLFIRI-BV →
    regimen-folfiri-bv）。識別名の書式でなければ None。"""
    if not isinstance(regimen, str):
        return None
    if regimen in REGIMEN_SKILL_NAMES:
        return REGIMEN_SKILL_NAMES[regimen]
    if len(regimen) > REGIMEN_CODE_MAX or not _REGIMEN_CODE_RE.fullmatch(regimen):
        return None
    return "regimen-" + regimen.lower()


def load_regimen_skill(
    regimen: Regimen | str, skills_dir: Path | None = None
) -> RegimenSkill:
    """識別名のレジメン Skill（FOLFOX → regimen-folfox、FOLFIRI-BV → regimen-folfiri-bv）。

    置かれていない・書式の違う識別名は unknown_regimen。
    """
    name = regimen_skill_name(regimen)
    if name is None:
        raise SkillValidationError("unknown_regimen", "未知のレジメン")
    try:
        skill = load_skill(name, skills_dir)
    except SkillNotFoundError:
        if regimen in REGIMEN_SKILL_NAMES:
            raise
        raise SkillValidationError("unknown_regimen", "未知のレジメン") from None
    if not isinstance(skill, RegimenSkill):  # 接頭辞で決まるので通常は起きない
        raise SkillValidationError("unknown_kind", f"{name} がレジメン Skill でない")
    if skill.regimen != regimen:
        raise SkillValidationError(
            "regimen_mismatch", f"{name} の regimen が {regimen} でない"
        )
    return skill


def load_report_skill(
    name: str = DEFAULT_REPORT_SKILL, skills_dir: Path | None = None
) -> ReportFormatSkill:
    skill = load_skill(name, skills_dir)
    if not isinstance(skill, ReportFormatSkill):
        raise SkillValidationError(
            "unknown_kind", f"{name} がレポート形式 Skill でない"
        )
    return skill
