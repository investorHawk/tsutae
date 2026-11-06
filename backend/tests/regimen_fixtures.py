"""D4 レジメンのテスト用フォーム（plan-d4-regimen.md §5 の3つ）。

値はテストとデモのための例（先生が確かめる）。薬の量は持たない。合成記録・評価は作らない。
質問は §5 の目安から: 部品集の既知の質問＋だるさ・出血（RAM はしびれも）。
"""

from __future__ import annotations

from typing import Any

from tsutae.regimen import RegimenForm

# 部品集の既知の質問（FOLFOX/CAPOX の frontmatter と同じ文）
KNOWN_QUESTIONS: dict[str, dict[str, str]] = {
    "numbness": {
        "label": "しびれ",
        "text": "手足のしびれや冷たいものがさわりにくい感じはありましたか",
        "answer_type": "three_level",
    },
    "diarrhea": {
        "label": "下痢",
        "text": "下痢はありましたか",
        "answer_type": "three_level",
    },
    "stomatitis": {
        "label": "口内炎",
        "text": "口の中の痛みや口内炎はありましたか",
        "answer_type": "three_level",
    },
    "nausea_appetite": {
        "label": "吐き気・食欲",
        "text": "吐き気や食欲の落ち込みはありましたか",
        "answer_type": "three_level",
    },
    "fever": {
        "label": "体温",
        "text": "熱を測りましたか",
        "answer_type": "temperature",
    },
}
NEW_QUESTIONS: dict[str, dict[str, str]] = {
    "neuropathy": {
        "label": "しびれ",
        "text": "手足のしびれはありましたか",
        "answer_type": "three_level",
    },
    "fatigue": {
        "label": "だるさ",
        "text": "だるさや疲れやすさはありましたか",
        "answer_type": "three_level",
    },
    "bleeding": {
        "label": "出血",
        "text": "鼻血や歯ぐきからの出血はありましたか",
        "answer_type": "three_level",
    },
}
SIDE_EFFECTS: dict[str, dict[str, Any]] = {
    "neuropathy": {
        "phrases": ["手足のしびれ", "指先がピリピリする"],
        "ctcae_terms": ["末梢神経障害"],
        "question_key": "neuropathy",
    },
    "diarrhea": {
        "phrases": ["下痢", "お腹がゆるい"],
        "ctcae_terms": ["下痢"],
        "question_key": "diarrhea",
    },
    "stomatitis": {
        "phrases": ["口内炎", "口の中が痛い"],
        "ctcae_terms": ["口内炎", "口腔痛"],
        "question_key": "stomatitis",
    },
    "nausea_appetite": {
        "phrases": ["吐き気", "吐いた", "食欲がない"],
        "ctcae_terms": ["悪心", "嘔吐", "食欲不振"],
        "question_key": "nausea_appetite",
    },
    "fatigue": {
        "phrases": ["だるい", "疲れやすい"],
        "ctcae_terms": ["疲労", "倦怠感"],
        "question_key": "fatigue",
    },
    "bleeding": {
        "phrases": ["鼻血が出た"],
        "ctcae_terms": ["鼻出血"],
        "question_key": "bleeding",
    },
    "fever": {
        "phrases": ["熱が出た"],
        "ctcae_terms": ["発熱"],
        "question_key": "fever",
    },
    "myalgia": {
        "phrases": ["関節や筋肉が痛い"],
        "ctcae_terms": ["関節痛", "筋肉痛"],
        "question_key": None,
    },
}


def _questions(keys: list[str]) -> list[dict[str, Any]]:
    table = {**KNOWN_QUESTIONS, **NEW_QUESTIONS}
    return [{"row_id": f"q-{key}", "key": key, **table[key]} for key in keys]


def _side_effects(keys: list[str]) -> list[dict[str, Any]]:
    return [{"row_id": f"se-{key}", **SIDE_EFFECTS[key]} for key in keys]


def _days(*ranges: tuple[int, int]) -> list[dict[str, int]]:
    return [{"start": s, "end": e} for s, e in ranges]


def _infusion(row_id: str, name: str, *ranges: tuple[int, int]) -> dict[str, Any]:
    return {"row_id": row_id, "name": name, "route": "infusion", "days": _days(*ranges)}


def ram_wptx_data() -> dict[str, Any]:
    return {
        "basic": {
            "display_name": "RAM＋wPTX",
            "code": "RAM-WPTX",
            "target": "胃がん",
            "cycle_days": 28,
        },
        "drugs": [
            _infusion("d-ptx", "パクリタキセル", (1, 1), (8, 8), (15, 15)),
            _infusion("d-ram", "ラムシルマブ", (1, 1), (15, 15)),
        ],
        "side_effects": _side_effects(
            [
                "neuropathy",
                "diarrhea",
                "stomatitis",
                "nausea_appetite",
                "fatigue",
                "bleeding",
                "fever",
                "myalgia",
            ]
        ),
        "questions": _questions(
            [
                "neuropathy",
                "diarrhea",
                "stomatitis",
                "nausea_appetite",
                "fatigue",
                "bleeding",
                "fever",
            ]
        ),
        "notes": "手足のむくみは用語の一覧に無いので、出来事にせず引用に残す",
    }


def folfiri_bv_data() -> dict[str, Any]:
    return {
        "basic": {
            "display_name": "FOLFIRI＋BV",
            "code": "FOLFIRI-BV",
            "target": "大腸がん",
            "cycle_days": 14,
        },
        "drugs": [
            _infusion("d-bv", "ベバシズマブ", (1, 1)),
            _infusion("d-iri", "イリノテカン", (1, 1)),
            _infusion("d-lv", "レボホリナート", (1, 1)),
            _infusion("d-fu", "フルオロウラシル（急速静注）", (1, 1)),
            {
                "row_id": "d-fu-pump",
                "name": "フルオロウラシル（46時間）",
                "route": "pump",
                "days": _days((1, 3)),
            },
        ],
        "side_effects": _side_effects(
            [
                "diarrhea",
                "nausea_appetite",
                "stomatitis",
                "fatigue",
                "bleeding",
                "fever",
            ]
        ),
        "questions": _questions(
            [
                "diarrhea",
                "nausea_appetite",
                "stomatitis",
                "fatigue",
                "bleeding",
                "fever",
            ]
        ),
        "notes": "",
    }


def lonsurf_bv_data() -> dict[str, Any]:
    return {
        "basic": {
            "display_name": "ロンサーフ＋BV",
            "code": "LONSURF-BV",
            "target": "大腸がん",
            "cycle_days": 28,
        },
        "drugs": [
            {
                "row_id": "d-ftd",
                "name": "トリフルリジン・チピラシル",
                "route": "oral",
                "days": _days((1, 5), (8, 12)),
                "times_per_day": 2,
                "start_note": "Day1 の朝から",
            },
            _infusion("d-bv", "ベバシズマブ", (1, 1), (15, 15)),
        ],
        "side_effects": _side_effects(
            ["nausea_appetite", "diarrhea", "fatigue", "bleeding", "fever"]
        ),
        "questions": _questions(
            ["nausea_appetite", "diarrhea", "fatigue", "bleeding", "fever"]
        ),
        "notes": "飲み薬は1日2回（朝・夕食後）。",
    }


EXTRA_REGIMENS = {
    "ram_wptx": ram_wptx_data,
    "folfiri_bv": folfiri_bv_data,
    "lonsurf_bv": lonsurf_bv_data,
}


def extra_form(name: str) -> RegimenForm:
    return RegimenForm.model_validate(EXTRA_REGIMENS[name]())


def fill_patch(base: RegimenForm, target: RegimenForm) -> Any:
    """base（新しい下書きの空のフォーム）を target の値にする FormPatch（テスト用）。

    base の行を全て消して target の行を同じ順に足し、全ての欄（識別名を含む）を target の
    値にする（行の並びも target と同じになる）。
    """
    from tsutae.regimen.edit import FieldChange, FormPatch, RowAdd
    from tsutae.regimen.form import field_ids

    sections = ("drugs", "side_effects", "questions")
    deletes = tuple(f"{s}.{r.row_id}" for s in sections for r in getattr(base, s))
    adds = tuple(RowAdd(s, r.row_id) for s in sections for r in getattr(target, s))
    data = target.model_dump(mode="json")
    changes = []
    for fid in field_ids(target):
        parts = fid.split(".")
        if len(parts) == 1:
            value = data[parts[0]]
        elif len(parts) == 2:
            value = data[parts[0]][parts[1]]
        else:
            row = next(r for r in data[parts[0]] if r["row_id"] == parts[1])
            value = row[parts[2]]
        changes.append(FieldChange(fid, value))
    return FormPatch(changes=tuple(changes), adds=adds, deletes=deletes)
