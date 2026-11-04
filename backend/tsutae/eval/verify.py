"""保存済みの予測を合成データと照合する（`--cache-only`）。症例は全て合成。

`cache.check_prepared` はファイルの中の辻褄しか見ない。entry_ids・masked_texts・
input.entries から同じ記録を揃えて消したファイルや、患者IDを入れ替えたファイルは
それを通り、消した記録のラベルが「今回の入力に無い記録」として黙って分母から外れる。
ここでは合成データから `prepare_input`（純関数。API は呼ばない）で入力を作り直し、
保存済みの入力と比べて、違えば拒否する。

比べるのは記録の選別に関わる項目だけ（entry_ids・masked_texts・unprocessed・
input.entries・input.schedule）。Skill の版（regimen_skill_version 等）は比べない
（Skill を直しただけで過去の予測が読めなくならないように）。伏せ字の規則を変えると
masked_free_text が変わるので、それより前の予測は拒否される。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tsutae.eval.cache import CoursePrediction, sanitize_prepared
from tsutae.eval.cases import EvalCase, eval_cases
from tsutae.eval.predict import PrepareFn, build_prepared
from tsutae.schemas import PreparedInput


def _differences(saved: PreparedInput, rebuilt: PreparedInput) -> list[str]:
    """違う項目の名前（本文は入れない）。"""
    pairs = {
        "entry_ids": (saved.entry_ids, rebuilt.entry_ids),
        "masked_texts": (saved.masked_texts, rebuilt.masked_texts),
        "unprocessed": (saved.unprocessed, rebuilt.unprocessed),
        "input.entries": (saved.input.entries, rebuilt.input.entries),
        "input.schedule": (saved.input.schedule, rebuilt.input.schedule),
    }
    return [name for name, (a, b) in pairs.items() if a != b]


def verify_prediction(
    prediction: CoursePrediction,
    case: EvalCase,
    *,
    prepare_fn: PrepareFn,
    skills_dir: Path | None = None,
) -> None:
    """合成データから作り直した入力と合わなければ ValueError。"""
    name = prediction.file_name
    if prediction.visit_date != case.visit_date:
        raise ValueError(f"{name}: 基準日がこのコースの最終日と違う")
    rebuilt = sanitize_prepared(
        build_prepared(case, prepare_fn=prepare_fn, skills_dir=skills_dir)
    )
    diff = _differences(prediction.prepared, rebuilt)
    if diff:
        raise ValueError(
            f"{name}: 保存済みの入力が合成データから作った入力と違う（{', '.join(diff)}）"
        )


def verify_predictions(
    predictions: Sequence[CoursePrediction],
    *,
    data_dir: Path,
    prepare_fn: PrepareFn,
    skills_dir: Path | None = None,
) -> None:
    """全ての予測を照合する。評価用の患者・コースに無いものも拒否する。"""
    cases = {(c.patient.patient_id, c.course_no): c for c in eval_cases(data_dir)}
    for p in predictions:
        case = cases.get((p.patient_id, p.course_no))
        if case is None:
            raise ValueError(f"{p.file_name}: 評価用の患者・コースに無い")
        verify_prediction(p, case, prepare_fn=prepare_fn, skills_dir=skills_dir)
