"""D4 レジメンのフォーム（正本）と欄の id・出どころ（spec 9.1・architecture 9c）。

- `RegimenForm` は下書きの途中の形も持てる（必須の欄が None・空でもよい）。値の検査は
  `tsutae.regimen.validate`、描画は `tsutae.regimen.render`
- 型だけを pydantic で固める（frozen・extra=forbid・strict）。規則（日数の範囲・薬の量・
  H1 など）は欄の id つきで返したいので validate.py に置く
- `prose` は画面に出さない描画用の文。Claude も医師も書けない（`field_ids` に入れない）
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, RootModel

from tsutae.config import PACKAGE_ROOT
from tsutae.schemas import AnswerType

Route = Literal["infusion", "oral", "pump"]
FieldSource = Literal["doctor_text", "standard", "doctor_edit"]

BUILTIN_FORMS_DIR = PACKAGE_ROOT / "skills" / "regimen_forms"
# 評価済みの版の form JSON（Skill 名 → ファイル）
_BUILTIN_FILES = {"regimen-folfox": "folfox.json", "regimen-capox": "capox.json"}


class _FormModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class DayRange(_FormModel):
    """Day の範囲（両端を含む）。1日だけなら start == end。"""

    start: int
    end: int


class BasicInfo(_FormModel):
    display_name: str | None = None
    code: str | None = None
    target: str | None = None  # 画面と一覧だけ。SKILL.md には描かない
    cycle_days: int | None = None


class DrugRow(_FormModel):
    row_id: str
    name: str | None = None
    route: Route | None = None
    days: list[DayRange] = []
    times_per_day: int | None = None  # 内服だけ
    start_note: str | None = None  # 内服だけ（例: 「Day1 の夕方から」）


class SideEffectRow(_FormModel):
    row_id: str
    phrases: list[str] = []
    ctcae_terms: list[str] = []
    question_key: str | None = None


class QuestionRow(_FormModel):
    row_id: str
    key: str | None = None
    label: str | None = None  # 短い名前。frontmatter には書かない
    text: str | None = None
    answer_type: AnswerType | None = None


class ContradictionExample(_FormModel):
    """§5 食い違いの例の行（クローズ「<closed_label> なし」＋自由記載「<quote>」）。"""

    closed_label: str
    question_key: str
    quote: str


class RegimenProse(_FormModel):
    """フォームの欄に無い描画用の文。None・空の欄は既定の文（render.py）。"""

    intro_note: str = ""  # 「症例は全て合成（架空）」の前に置く注記
    cycle_note: str = ""  # 「1コースは21日」の直後（例:「（3週）」）
    day1_note: str = "外来で点滴した日"  # 「Day1 = 実投与日」の括弧の中
    pump_sentence: str | None = None  # 持続ポンプの文
    no_pump_note: str = ""  # 「持続ポンプは無い」の括弧の頭
    oral_note: str = ""  # 内服の文の末尾
    improving_examples: list[str] | None = None
    contradiction_example: ContradictionExample | None = None


class RegimenForm(_FormModel):
    basic: BasicInfo = BasicInfo()
    drugs: list[DrugRow] = []
    side_effects: list[SideEffectRow] = []
    questions: list[QuestionRow] = []
    notes: str = ""
    prose: RegimenProse | None = None


class FieldSources(RootModel[dict[str, FieldSource]]):
    """欄の id → 出どころ（先生の文から／標準の値／先生が直接入れた）。"""

    model_config = ConfigDict(frozen=True, strict=True)


# ---------------------------------------------------------------------------
# 欄の id
# ---------------------------------------------------------------------------

BASIC_FIELDS = ("display_name", "code", "target", "cycle_days")
DRUG_FIELDS = ("name", "route", "days", "times_per_day", "start_note")
SIDE_EFFECT_FIELDS = ("phrases", "ctcae_terms", "question_key")
QUESTION_FIELDS = ("key", "label", "text", "answer_type")


def field_ids(form: RegimenForm) -> tuple[str, ...]:
    """医師・Claude が書ける欄の id（`basic.cycle_days`・`drugs.<row_id>.days` など）。"""
    ids = [f"basic.{f}" for f in BASIC_FIELDS]
    for section, rows, fields in (
        ("drugs", form.drugs, DRUG_FIELDS),
        ("side_effects", form.side_effects, SIDE_EFFECT_FIELDS),
        ("questions", form.questions, QUESTION_FIELDS),
    ):
        seen: set[str] = set()
        for row in rows:
            if row.row_id in seen:  # 重複した行は validate_form が咎める
                continue
            seen.add(row.row_id)
            ids.extend(f"{section}.{row.row_id}.{f}" for f in fields)
    ids.append("notes")
    return tuple(ids)


def unknown_source_ids(form: RegimenForm, sources: FieldSources) -> list[str]:
    """フォームに無い欄を指している出どころの id（並びは sources の順）。"""
    known = set(field_ids(form))
    return [fid for fid in sources.root if fid not in known]


def prune_sources(form: RegimenForm, sources: FieldSources) -> FieldSources:
    """消えた行・欄の出どころを落とした新しい FieldSources（元は変えない）。"""
    known = set(field_ids(form))
    return FieldSources({k: v for k, v in sources.root.items() if k in known})


# ---------------------------------------------------------------------------
# 読み込み
# ---------------------------------------------------------------------------


def load_form_json(text: str | bytes) -> RegimenForm:
    """form JSON（`regimen_forms` 表・リポジトリの JSON）を読む。形が違えば ValidationError。"""
    return RegimenForm.model_validate_json(text)


def builtin_form_path(skill_name: str) -> Path:
    try:
        return BUILTIN_FORMS_DIR / _BUILTIN_FILES[skill_name]
    except KeyError:
        raise KeyError(f"{skill_name} の form JSON は無い") from None


def load_builtin_form(skill_name: str) -> RegimenForm:
    """評価済みの版（regimen-folfox@1・regimen-capox@1）の form JSON。"""
    return load_form_json(builtin_form_path(skill_name).read_bytes())
