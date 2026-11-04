"""依頼文とツールで行を指す ref（`drugs.1`）と、フォームの row_id の対応（T94）。

row_id は画面が決める（`d-oxaliplatin`・`q-fever` など）。この形は H1（二次検出の
id_like）に掛かるので、依頼文に row_id を出すと全ての往復が止まる。そこで依頼文と
Claude のツールの入力では、行を「節＋番号」の ref で指す（`drugs.4.days`）。

- `RowHandles` は1往復の間だけの対応（frozen。`bind`・`unbind` は新しいものを返す）。
  番号は往復の始まりの行の並び（1から）。足した行には Claude が空いた番号を付ける。
  一度使った番号は同じ往復の中で使い回さない（消した行と取り違えない）
- `field_id(ref)` は欄の ref を `apply_patch` の欄の id に直す（基本・補足はそのまま）。
  `ref(field_id)` は逆向き（ツールの結果・依頼文に欄を示すとき）
- `new_row_id` は Claude が足した行の row_id（`drug1`・`effect1`・`question1`。H1 に
  掛からない形）
- `form_view`・`sources_view` は依頼文に入れるフォームと出どころ（row_id・prose を除く）
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from tsutae.regimen.form import (
    BASIC_FIELDS,
    DRUG_FIELDS,
    QUESTION_FIELDS,
    SIDE_EFFECT_FIELDS,
    FieldSources,
    RegimenForm,
)

__all__ = [
    "MAX_REF_NUMBER",
    "ROW_FIELDS",
    "SECTIONS",
    "RowHandles",
    "form_view",
    "new_row_id",
    "sources_view",
]

SECTIONS = ("drugs", "side_effects", "questions")
ROW_FIELDS: Mapping[str, tuple[str, ...]] = {
    "drugs": DRUG_FIELDS,
    "side_effects": SIDE_EFFECT_FIELDS,
    "questions": QUESTION_FIELDS,
}
_NEW_ROW_PREFIX = {"drugs": "drug", "side_effects": "effect", "questions": "question"}
MAX_REF_NUMBER = 99
_ROW_REF_RE = re.compile(r"^(drugs|side_effects|questions)\.([1-9][0-9]?)$")
_TOP_FIELDS = frozenset({*(f"basic.{f}" for f in BASIC_FIELDS), "notes"})


@dataclass(frozen=True)
class RowHandles:
    """行の ref（`drugs.1`）→ row_id。`used` は往復の中で一度でも使った ref。"""

    rows: Mapping[str, str] = field(default_factory=dict)
    used: frozenset[str] = frozenset()

    @classmethod
    def from_form(cls, form: RegimenForm) -> RowHandles:
        rows: dict[str, str] = {}
        for section in SECTIONS:
            for i, row in enumerate(getattr(form, section), start=1):
                rows[f"{section}.{i}"] = row.row_id
        return cls(rows=rows, used=frozenset(rows))

    # -- 行 -----------------------------------------------------------------

    def row_id(self, ref: str) -> str | None:
        return self.rows.get(ref)

    def ref_of_row(self, section: str, row_id: str) -> str | None:
        prefix = f"{section}."
        return next(
            (
                r
                for r, rid in self.rows.items()
                if r.startswith(prefix) and rid == row_id
            ),
            None,
        )

    def is_free(self, ref: str) -> bool:
        """行を足すのに使える ref か（形が合い、この往復でまだ使っていない）。"""
        return _ROW_REF_RE.fullmatch(ref) is not None and ref not in self.used

    def next_free(self, section: str) -> str | None:
        """その節で空いている最小の ref（propose_questions が足す行に使う）。"""
        return next(
            (
                f"{section}.{n}"
                for n in range(1, MAX_REF_NUMBER + 1)
                if self.is_free(f"{section}.{n}")
            ),
            None,
        )

    def bind(self, ref: str, row_id: str) -> RowHandles:
        return RowHandles(rows={**self.rows, ref: row_id}, used=self.used | {ref})

    def unbind(self, ref: str) -> RowHandles:
        return RowHandles(
            rows={r: rid for r, rid in self.rows.items() if r != ref}, used=self.used
        )

    # -- 欄 -----------------------------------------------------------------

    def field_id(self, ref: str) -> str | None:
        """欄の ref（`drugs.4.days`・`basic.code`・`notes`）→ 欄の id。無ければ None。"""
        if ref in _TOP_FIELDS:
            return ref
        row_ref, _, name = ref.rpartition(".")
        match = _ROW_REF_RE.fullmatch(row_ref)
        if match is None or name not in ROW_FIELDS[match.group(1)]:
            return None
        row_id = self.rows.get(row_ref)
        return None if row_id is None else f"{match.group(1)}.{row_id}.{name}"

    def ref(self, field_id: str) -> str:
        """欄の id（または `drugs.<row_id>`）→ ref。対応が無ければ節の名前だけ。"""
        section, _, rest = field_id.partition(".")
        if section not in SECTIONS or not rest:
            return field_id
        row_id, _, name = rest.partition(".")
        row_ref = self.ref_of_row(section, row_id)
        if row_ref is None:
            return section
        return f"{row_ref}.{name}" if name else row_ref


def new_row_id(section: str, form: RegimenForm, *, taken: frozenset[str]) -> str:
    """Claude が足す行の row_id（`question1` など。form の行と taken に無い最小の番号）。"""
    prefix = _NEW_ROW_PREFIX[section]
    existing = {row.row_id for row in getattr(form, section)} | taken
    n = 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def form_view(form: RegimenForm, handles: RowHandles) -> dict[str, Any]:
    """依頼文に入れるフォーム（行は ref つき。row_id と prose は入れない）。"""
    data = form.model_dump(mode="json", exclude={"prose"})
    view: dict[str, Any] = {"basic": data["basic"]}
    for section in SECTIONS:
        rows = []
        for row in data[section]:
            ref = handles.ref_of_row(section, row["row_id"]) or section
            rows.append({"ref": ref, **{k: v for k, v in row.items() if k != "row_id"}})
        view[section] = rows
    view["notes"] = data["notes"]
    return view


def sources_view(sources: FieldSources, handles: RowHandles) -> dict[str, str]:
    """欄の出どころを ref で（依頼文用）。"""
    return {handles.ref(fid): src for fid, src in sources.root.items()}
