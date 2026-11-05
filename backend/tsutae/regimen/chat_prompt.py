"""D4 レジメンの1往復の依頼文（T94。architecture 9c「1往復」、plan-d4-regimen §5）。

本文はこのファイルの文字列の定数（`SYSTEM_PROMPT`・`_PROMPT_TEMPLATE`・`_RULES`）。
`build_turn_prompt(draft, text)` は純関数で、次を埋める:

- 今のフォーム（JSON。行は ref `drugs.1` で示し、row_id・prose は入れない。row_id は
  H1 の id_like に掛かる形があるため。chat_handles）
- 欄の出どころ（先生が直接入れた欄・AI が入れた欄）と、まだ入っていない必須の欄
- 部品集（key・短い名前・文）と CTCAE の用語の一覧（ctcae_terms.json の用語名）
- 直近の会話（`HISTORY_ROWS` 行。先生の文・Claude の返答・聞いた問い。欄の id は出さない）。
  聞いた問いの選択肢は「」で囲んでつなぐ（`ask_line`。空白・「/」は H1 の long_digits の
  区切りなので、数字の選択肢 7・14・21・28 が1つの数字の並びになる）。描いた行が H1 に
  掛かれば固定の文（`HISTORY_HIDDEN`）に置き換える（その行のせいで往復が止まらないように）
- 規則と先生の文（<<< と >>> の間）

API はこの関数で作った文の全体に detect_identifiers を掛けてから Claude を呼ぶ。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any

from tsutae.masking import detect_identifiers
from tsutae.regimen.chat_handles import RowHandles, form_view, sources_view
from tsutae.regimen.chat_types import LibraryItem, TurnInput
from tsutae.regimen.validate import missing_fields
from tsutae.synthetic import load_terms

__all__ = [
    "HISTORY_HIDDEN",
    "HISTORY_ROWS",
    "SYSTEM_PROMPT",
    "ask_line",
    "build_turn_prompt",
    "term_names",
]

# 直近の会話の行数（先生の文と Claude の返答で4往復ほど）
HISTORY_ROWS = 8
_NONE = "（まだ無い）"
# 描くと H1 に掛かる会話の行の代わり
HISTORY_HIDDEN = "（この行は個人を特定しうる表現の疑いがあるので省いた）"

SYSTEM_PROMPT = (
    "あなたは外来化学療法の記録アプリ「つたえ」で、医師がレジメン（投与スケジュール・"
    "注意する症状・患者への質問）のフォームを埋めるのを手伝う係。"
    "医師の1回の文に1回だけ答える。フォームの欄は専用のツール（set_fields・"
    "propose_questions）でだけ変え、迷ったら ask で1問だけ聞く。"
    "ファイルは読まない・書かない。最後に短い返答の文（何を変えたか・何を聞いているか）"
    "を書いて終える。返答の文は医師が院内の画面で読む。患者には届かない。"
    "薬の量（mg/m² など）は扱わない。Grade・重さの判定・助言・原因の推測を書かない。"
)

_FIELDS_GUIDE = """\
- basic.display_name（画面の名前）・basic.code（識別名。英大文字・数字・「-」。新しい\
レジメンだけ）・basic.target（対象。例: 大腸がん）・basic.cycle_days（1コースの日数。7〜42）
- drugs.N.name（薬の名前）・route（infusion=点滴／oral=内服／pump=持続ポンプ）・\
days（Day の範囲の配列 [{"start": 1, "end": 1}]。早い順・重ねない・隣り合わせない）・\
times_per_day（内服だけ。1日の回数）・start_note（内服だけ。例: Day1 の朝から）。\
持続ポンプは1剤まで・Day1 から始まる範囲1つ。内服は1剤まで。Day1 に点滴を1剤以上置く
- side_effects.N.phrases（患者の言い方の配列）・ctcae_terms（下の用語の一覧の語の配列）・\
question_key（questions の key か null）
- questions.N.key（英小文字で始まる英小文字・数字・下線）・label（短い名前）・\
text（患者が読む文）・answer_type（three_level=なし・ある・つらい／temperature=体温）
- notes（補足の指示。施設の決まりなど、型に入らないこと）"""

_RULES = """\
- 値は set_fields の changes で渡す。先生の文から取った値は source=doctor_text、\
先生の文に無い値（標準の値として補ったもの）は source=standard を付ける。\
source=standard の値は採用の前に先生が確かめる
- 行を足すときは add_rows に今の番号と重ならない新しい ref（例: 今 drugs.3 まであれば \
drugs.4）を書き、同じ呼び出しの changes でその ref の欄を埋める。行を消すときは \
delete_rows に ref を書く
- 分からないこと・決められないことは推測で埋めず、ask で1問だけ、選択肢（2〜4）\
つきで聞く。聞いたら set_fields を続けず、返答の文で聞いていることを伝えて終える
- 薬の量（数値＋mg・mg/m²・mg/kg・AUC など）は欄に入れない
- 先生が直接入れた欄は、先生が変えるよう頼まない限り変えない。頼まれたときだけ \
overwrite_requested=true を付ける
- 体温の質問は外せない（38.0℃の固定規則の対象）
- 患者への質問は propose_questions で足す。基本・投与スケジュール・注意する症状が\
そろってから、注意する症状をもとに提案する（先生が文で質問を指定したときだけ、そろう前でも\
source=doctor_text で足す）。部品集にある質問は from_library で key を\
選ぶ。新しい質問は3択（なし・ある・つらい）で、短いやさしい独自の文にする（既存の\
質問票の文言を写さない。助言・説明・重さの基準を入れない）
- 新しい質問の目安: だるさ「だるさや疲れやすさはありましたか」、出血「鼻血や歯ぐき\
からの出血はありましたか」、パクリタキセルのしびれ「手足のしびれはありましたか」\
（オキサリプラチンの寒冷の文は使い回さない）、関節・筋肉の痛み、手足のむくみ
- 高血圧・蛋白尿・好中球減少・貧血は検査の値なので患者への質問にしない
- 用語の一覧に無い症状は ctcae_terms に入れず、notes に書く。一覧に無い症状の言い方を、\
近い用語の行の phrases に混ぜない（例: 歯肉出血は一覧に無いので、「歯ぐきから血が出る」を\
「鼻出血」の行に入れない）
- ツールがエラーや拒否を返したら、その呼び出しは何も受け付けていない。理由の欄を\
直してもう一度渡す
- 返答の文に患者の名前・番号などの個人を特定する語を書かない"""

_PROMPT_TEMPLATE = """\
医師がレジメンの画面のチャットに書いた文に、1回だけ答える。

## 今のフォーム（JSON。行は ref で指す。欄は「ref.欄の名前」: 例 drugs.1.days）
{form_json}

## 欄の出どころ
- 先生が直接入れた欄（頼まれない限り変えない）: {doctor_edit}
- AI が入れた欄（doctor_text=先生の文から／standard=標準の値）: {ai_sources}

## まだ入っていない必須の欄
{missing}

## 欄の決まり
{fields_guide}

## 質問の部品集（from_library で選べる。key: 短い名前「文」）
{library}

## CTCAE の用語の一覧（side_effects の ctcae_terms はこの中の語だけ）
{terms}

## 直近の会話
{history}

## 規則
{rules}

## 先生の文（<<< と >>> の間）
<<<
{text}
>>>
"""


@lru_cache(maxsize=1)
def term_names() -> tuple[str, ...]:
    """CTCAE の用語名（ctcae_terms.json の並び）。"""
    return tuple(item["term"] for item in load_terms())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def _join(items: Iterable[str]) -> str:
    listed = list(items)
    return "、".join(listed) if listed else "なし"


def _library_lines(library: Iterable[LibraryItem]) -> str:
    lines = [
        f"- {item.key}: {item.label}「{item.text}」"
        + ("（体温）" if item.answer_type == "temperature" else "")
        for item in library
    ]
    return "\n".join(lines) or _NONE


def ask_line(question: str, options: Iterable[str]) -> str:
    """聞いた問いの、依頼文の会話に入る形。選択肢は H1 の区切りでない「」で囲む。"""
    shown = "".join(f"「{o}」" for o in options)
    return f"（聞いた: {question} 選択肢: {shown}）"


def _ask_line(ask: Any) -> str:
    if not isinstance(ask, Mapping):
        return ""
    options = ask.get("options")
    listed = [str(o) for o in options] if isinstance(options, list) else []
    return ask_line(str(ask.get("question", "")), listed)


def _history_line(row: Mapping[str, Any]) -> str | None:
    role = row.get("role")
    if role == "doctor":
        return f"医師: {row.get('text', '')}"
    if role == "assistant":
        return f"あなた: {row.get('text', '')}{_ask_line(row.get('ask'))}"
    if role == "system":
        return "（この往復は失敗し、フォームは変わっていない）"
    return None


def _safe_line(line: str) -> str:
    return HISTORY_HIDDEN if detect_identifiers(line) else line


def _history(rows: Iterable[Mapping[str, Any]]) -> str:
    recent = list(rows)[-HISTORY_ROWS:]
    lines = [_safe_line(line) for line in map(_history_line, recent) if line]
    return "\n".join(lines) or _NONE


def build_turn_prompt(draft: TurnInput, text: str) -> str:
    """1往復の依頼文（純関数）。"""
    handles = RowHandles.from_form(draft.form)
    sources = sources_view(draft.sources, handles)
    doctor_edit = [ref for ref, src in sources.items() if src == "doctor_edit"]
    ai_sources = {ref: src for ref, src in sources.items() if src != "doctor_edit"}
    missing = [handles.ref(i.field_id) for i in missing_fields(draft.form)]
    return _PROMPT_TEMPLATE.format(
        form_json=_json(form_view(draft.form, handles)),
        doctor_edit=_join(doctor_edit),
        ai_sources=_json(ai_sources) if ai_sources else "なし",
        missing=_join(dict.fromkeys(missing)),
        fields_guide=_FIELDS_GUIDE,
        library=_library_lines(draft.library),
        terms=_join(term_names()),
        history=_history(draft.history),
        rules=_RULES,
        text=text,
    )
