"""tsutae.eval.metrics: 小さな手作りの予測とラベルで5指標を確かめる（症例は全て合成）。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tsutae.eval.metrics import RATIO_FIELDS, EvalResult, Ratio, aggregate, evaluate
from tsutae.schemas import (
    Contradiction,
    CourseSchedule,
    EntryLabel,
    LabelContradiction,
    LabelEvent,
    MaskedEntry,
    PipelineInput,
    PreparedInput,
    Question,
    Timeline,
    TimelineEvent,
    UnprocessedEntry,
)

D1 = date(2026, 9, 1)
ID_OFFSET = 10  # entry_no と entries.id（= seq）をずらして対応づけを確かめる


def _d(day: int) -> date:
    return D1 + timedelta(days=day - 1)


def _prepared(
    texts: dict[int, str],
    entry_ids: dict[int, int] | None = None,
    unprocessed: tuple[UnprocessedEntry, ...] = (),
):
    schedule = CourseSchedule(
        course_no=1,
        infusion_date=D1,
        day1_date=D1,
        last_day_date=_d(14),
        pump_removal_date=_d(3),
        previous_infusion_date=None,
        delay_days=None,
    )
    entries = [
        MaskedEntry(
            entry_no=no,
            record_date=_d(no),
            day=no,
            by_proxy=False,
            too_sick=False,
            masked_free_text=text,
        )
        for no, text in texts.items()
    ]
    pin = PipelineInput(
        regimen="FOLFOX",
        regimen_skill_version="regimen-folfox@1",
        report_skill_version="report-format-default@1",
        schedule=schedule,
        questions=[
            Question(
                key="diarrhea", text="下痢はありましたか", answer_type="three_level"
            )
        ],
        entries=entries,
    )
    ids = entry_ids if entry_ids is not None else {n: n + ID_OFFSET for n in texts}
    return PreparedInput(
        input=pin,
        entry_ids=ids,
        masked_texts=dict(texts),
        unprocessed=list(unprocessed),
    )


def _lev(term, qk, status, quote, day, recalled=False) -> LabelEvent:
    return LabelEvent(
        date=_d(day),
        day=day,
        course_no=1,
        term=term,
        question_key=qk,
        status=status,
        source_quote=quote,
        recalled=recalled,
    )


def _label(seq, events=(), contradictions=(), tags=(), unprocessed=False):
    return EntryLabel(
        entry_seq=seq,
        events=list(events),
        contradictions=list(contradictions),
        hard_case_tags=list(tags),
        expect_unprocessed=unprocessed,
    )


def _pev(no, term, qk, status, quote, day, recalled=False) -> TimelineEvent:
    return TimelineEvent(
        entry_no=no,
        date=_d(day),
        day=day,
        course_no=1,
        term=term,
        question_key=qk,
        status=status,
        source_quote=quote,
        confidence=0.9,
        recalled=recalled,
    )


def _pcon(no, qk, value, quote, day) -> Contradiction:
    return Contradiction(
        entry_no=no,
        date=_d(day),
        day=day,
        question_key=qk,
        closed_answer=value,
        free_text_quote=quote,
    )


def _ratio(r: Ratio) -> tuple[int, int]:
    return (r.numerator, r.denominator)


TEXT1 = "下痢が3回。吐き気はなかった。"
TEXT2 = "手先がすこしジンジンするくらい"
B_SEQ2_EVENTS = [
    _lev("食欲不振", "nausea_appetite", "present", "なんとなく食欲がない", 1),
    _lev("悪心", "nausea_appetite", "absent", "吐き気はない", 1),
]


def _basic_labels():
    return [
        _label(
            11,
            [
                _lev("下痢", "diarrhea", "present", "下痢が3回", 1),
                _lev("悪心", "nausea_appetite", "absent", "吐き気はなかった", 1),
            ],
            [
                LabelContradiction(
                    question_key="diarrhea",
                    closed_answer="none",
                    free_text_quote="下痢が3回",
                )
            ],
            tags=["contradiction", "negation"],
        ),
    ]


# ---------------------------------------------------------------------------
# Ratio
# ---------------------------------------------------------------------------


def test_ratio_rate_and_zero_denominator() -> None:
    assert Ratio(numerator=1, denominator=4).rate == pytest.approx(0.25)
    assert Ratio(numerator=0, denominator=0).rate is None


def test_ratio_rejects_numerator_above_denominator() -> None:
    with pytest.raises(ValueError):
        Ratio(numerator=2, denominator=1)


# ---------------------------------------------------------------------------
# 完全一致
# ---------------------------------------------------------------------------


def test_perfect_prediction_scores_everything() -> None:
    prepared = _prepared({1: TEXT1})
    predicted = Timeline(
        events=[
            _pev(1, "下痢", "diarrhea", "present", "下痢が3回", 1),
            _pev(1, "悪心", "nausea_appetite", "absent", "吐き気はなかった", 1),
        ],
        contradictions=[_pcon(1, "diarrhea", "none", "下痢が3回", 1)],
    )
    result = evaluate(predicted, prepared, _basic_labels())
    assert isinstance(result, EvalResult)
    assert _ratio(result.date) == (2, 2)
    assert _ratio(result.matched) == (2, 2)
    assert _ratio(result.term) == (2, 2)
    assert _ratio(result.contradiction_recall) == (1, 1)
    assert _ratio(result.contradiction_precision) == (1, 1)
    assert _ratio(result.negation_as_present) == (0, 1)
    assert _ratio(result.mild_as_absent) == (0, 0)
    assert _ratio(result.quote) == (2, 2)  # 出来事の source_quote だけ
    assert _ratio(result.contradiction_quote) == (1, 1)  # 参考（食い違いの引用）
    assert result.failures == []
    assert result.course_no == 1
    assert result.label_events == 2
    assert result.entries_evaluated == 1


# ---------------------------------------------------------------------------
# ① 日付
# ---------------------------------------------------------------------------


def test_date_off_by_one_is_date_failure_only() -> None:
    prepared = _prepared({1: "きのうから下痢"})
    labels = [_label(11, [_lev("下痢", "diarrhea", "present", "下痢", 1)])]
    predicted = Timeline(events=[_pev(1, "下痢", "diarrhea", "present", "下痢", 2)])
    result = evaluate(predicted, prepared, labels, patient_id="P-TEST0001")
    assert _ratio(result.date) == (0, 1)
    assert _ratio(result.term) == (1, 1)
    assert [f.metric for f in result.failures] == ["date"]
    failure = result.failures[0]
    assert failure.entry_seq == 11
    assert failure.patient_id == "P-TEST0001"
    assert failure.course_no == 1
    assert "2026-09-01" in failure.expected and "Day1" in failure.expected
    assert "2026-09-02" in failure.predicted and "Day2" in failure.predicted
    assert "下痢" in failure.item


def test_day_mismatch_alone_is_date_failure() -> None:
    prepared = _prepared({1: "下痢"})
    labels = [_label(11, [_lev("下痢", "diarrhea", "present", "下痢", 1)])]
    wrong_day = _pev(1, "下痢", "diarrhea", "present", "下痢", 1).model_copy(
        update={"day": 2}
    )
    result = evaluate(Timeline(events=[wrong_day]), prepared, labels)
    assert _ratio(result.date) == (0, 1)


# ---------------------------------------------------------------------------
# ② 用語
# ---------------------------------------------------------------------------


def test_term_mismatch_with_same_question_key_still_matches_for_date() -> None:
    prepared = _prepared({1: TEXT2})
    labels = [_label(11, [_lev("口腔痛", "stomatitis", "present", TEXT2, 1)])]
    predicted = Timeline(events=[_pev(1, "口内炎", "stomatitis", "present", TEXT2, 1)])
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.term) == (0, 1)
    assert _ratio(result.matched) == (1, 1)
    assert _ratio(result.date) == (1, 1)
    [failure] = result.failures
    assert failure.metric == "term"
    assert failure.expected == "口腔痛"
    assert "口内炎" in failure.predicted


def test_term_without_question_key_has_no_fallback() -> None:
    prepared = _prepared({1: "だるい"})
    labels = [_label(11, [_lev("倦怠感", None, "present", "だるい", 1)])]
    predicted = Timeline(events=[_pev(1, "疲労", None, "present", "だるい", 1)])
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.term) == (0, 1)
    assert _ratio(result.matched) == (0, 1)
    assert _ratio(result.date) == (0, 1)  # 対応づけできない出来事は日付も不一致
    assert _ratio(result.date_paired) == (0, 0)
    assert result.date_paired.rate is None
    assert [f.metric for f in result.failures] == ["term"]


def test_duplicate_term_in_one_entry_is_matched_one_to_one() -> None:
    text = "点滴の次の日から下痢。きょうも下痢"
    prepared = _prepared({1: text})
    labels = [
        _label(
            11,
            [
                _lev("下痢", "diarrhea", "present", "点滴の次の日から下痢", 2, True),
                _lev("下痢", "diarrhea", "present", "きょうも下痢", 4),
            ],
            tags=["relative_time"],
        )
    ]
    only_today = Timeline(events=[_pev(1, "下痢", "diarrhea", "present", "下痢", 4)])
    result = evaluate(only_today, prepared, labels)
    assert _ratio(result.term) == (2, 2)  # 同じ記録に同じ用語の予測がある
    assert _ratio(result.matched) == (1, 2)
    assert _ratio(result.date) == (1, 2)
    assert _ratio(result.date_paired) == (1, 1)  # 近い日付の予測に対応づく
    assert [f.metric for f in result.failures] == ["match"]
    assert "Day2" in result.failures[0].expected

    both_reversed = Timeline(
        events=[
            _pev(1, "下痢", "diarrhea", "present", "きょうも下痢", 4),
            _pev(1, "下痢", "diarrhea", "present", "点滴の次の日から下痢", 2, True),
        ]
    )
    result2 = evaluate(both_reversed, prepared, labels)
    assert _ratio(result2.date) == (2, 2)
    assert result2.failures == []


def test_prediction_is_not_reused_across_label_events() -> None:
    text = "口内炎。口の中が痛い"
    prepared = _prepared({1: text})
    labels = [
        _label(
            11,
            [
                _lev("口内炎", "stomatitis", "improving", "口内炎", 1),
                _lev("口腔痛", "stomatitis", "present", "口の中が痛い", 1),
            ],
        )
    ]
    predicted = Timeline(
        events=[_pev(1, "口腔痛", "stomatitis", "present", "口の中が痛い", 1)]
    )
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.matched) == (1, 2)
    assert _ratio(result.term) == (1, 2)


def _snapshot(result: EvalResult) -> tuple:
    ratios = tuple(_ratio(getattr(result, name)) for name in RATIO_FIELDS)
    failures = sorted(
        (f.entry_seq or 0, f.metric, f.item, f.expected, f.predicted)
        for f in result.failures
    )
    return ratios, failures


def test_result_does_not_depend_on_label_event_order() -> None:
    # 患者B seq2 と同じ形。用語を間違えた予測1件が、status の同じラベルに対応づく
    text = "なんとなく食欲がない。吐き気はない。"
    prepared = _prepared({1: text})
    predicted = Timeline(
        events=[
            _pev(1, "嘔吐", "nausea_appetite", "present", "なんとなく食欲がない", 1)
        ]
    )
    as_is = [_label(11, B_SEQ2_EVENTS, tags=["negation"])]
    flipped = [_label(11, list(reversed(B_SEQ2_EVENTS)), tags=["negation"])]
    first = evaluate(predicted, prepared, as_is)
    second = evaluate(predicted, prepared, flipped)
    assert _ratio(first.negation_as_present) == (0, 1)
    assert _snapshot(first) == _snapshot(second)


def test_status_breaks_ties_for_improving_and_present_with_same_key() -> None:
    # 患者A seq22 と同じ形: 同じ日・同じ key で improving と present
    text = "しびれはほとんど気にならない。つめたい物はまだ少しピリッとする"
    prepared = _prepared({1: text})
    events = [
        _lev("末梢神経障害", "numbness", "improving", "しびれは", 1),
        _lev("末梢神経障害", "numbness", "present", "ピリッとする", 1),
    ]
    predicted = Timeline(
        events=[_pev(1, "知覚過敏", "numbness", "improving", "しびれは", 1)]
    )
    for ordered in (events, list(reversed(events))):
        result = evaluate(predicted, prepared, [_label(11, ordered)])
        assert _ratio(result.mild_missed) == (0, 1)


# ---------------------------------------------------------------------------
# ③ 食い違い
# ---------------------------------------------------------------------------


def test_contradiction_missed_and_spurious() -> None:
    prepared = _prepared({1: TEXT1, 2: TEXT2})
    labels = _basic_labels() + [
        _label(12, [_lev("末梢神経障害", "numbness", "present", TEXT2, 2)])
    ]
    predicted = Timeline(
        events=[
            _pev(1, "下痢", "diarrhea", "present", "下痢が3回", 1),
            _pev(2, "末梢神経障害", "numbness", "present", TEXT2, 2),
        ],
        contradictions=[_pcon(2, "numbness", "none", TEXT2, 2)],
    )
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.contradiction_recall) == (0, 1)
    assert _ratio(result.contradiction_precision) == (0, 1)
    metrics = sorted(f.metric for f in result.failures if "contradiction" in f.metric)
    assert metrics == ["contradiction_missed", "contradiction_spurious"]
    missed = next(f for f in result.failures if f.metric == "contradiction_missed")
    assert missed.entry_seq == 11 and "diarrhea" in missed.item
    spurious = next(f for f in result.failures if f.metric == "contradiction_spurious")
    assert spurious.entry_seq == 12 and "numbness" in spurious.item


def test_contradiction_matches_by_entry_and_question_key() -> None:
    prepared = _prepared({1: TEXT1})
    predicted = Timeline(
        contradictions=[
            _pcon(1, "diarrhea", "present", "吐き気はなかった", 1),
            _pcon(1, "diarrhea", "none", "下痢が3回", 1),  # 重複は1件に数える
        ],
    )
    result = evaluate(predicted, prepared, _basic_labels())
    assert _ratio(result.contradiction_recall) == (1, 1)
    assert _ratio(result.contradiction_precision) == (1, 1)


def test_no_contradictions_anywhere_gives_none_rates() -> None:
    prepared = _prepared({1: "下痢"})
    labels = [_label(11, [_lev("下痢", "diarrhea", "present", "下痢", 1)])]
    result = evaluate(Timeline(), prepared, labels)
    assert result.contradiction_recall.rate is None
    assert result.contradiction_precision.rate is None


# ---------------------------------------------------------------------------
# ④ 軽い・改善中 / 否定
# ---------------------------------------------------------------------------


def test_improving_predicted_absent_is_counted() -> None:
    text = "しびれはだいぶ楽"
    prepared = _prepared({1: text})
    labels = [_label(11, [_lev("末梢神経障害", "numbness", "improving", text, 1)])]
    predicted = Timeline(
        events=[_pev(1, "末梢神経障害", "numbness", "absent", text, 1)]
    )
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.mild_as_absent) == (1, 1)
    assert _ratio(result.mild_missed) == (0, 1)
    [failure] = result.failures
    assert failure.metric == "mild_as_absent"
    assert failure.expected == "improving" and failure.predicted == "absent"


def test_mild_tagged_present_is_not_a_mild_target() -> None:
    # mild_improving は記録のタグ。present の出来事まで「軽い・改善中」に広げない
    prepared = _prepared({1: TEXT2})
    labels = [
        _label(
            11,
            [_lev("末梢神経障害", "numbness", "present", TEXT2, 1)],
            tags=["mild_improving"],
        )
    ]
    result = evaluate(Timeline(), prepared, labels)
    assert _ratio(result.mild_missed) == (0, 0)
    assert _ratio(result.mild_as_absent) == (0, 0)
    assert "mild_missed" not in [f.metric for f in result.failures]


def test_mild_targets_are_improving_events_only() -> None:
    # 患者B seq8 と同じ形: タグ付きの記録に present 2件と improving 1件
    text = "口内炎はまだ1つのこってる。食欲はもどってきた。味がしない"
    prepared = _prepared({1: text})
    labels = [
        _label(
            11,
            [
                _lev(
                    "口内炎",
                    "stomatitis",
                    "present",
                    "口内炎はまだ1つのこってる",
                    1,
                ),
                _lev(
                    "食欲不振", "nausea_appetite", "improving", "食欲はもどってきた", 1
                ),
                _lev("味覚異常", None, "present", "味がしない", 1),
            ],
            tags=["contradiction", "mild_improving"],
        )
    ]
    result = evaluate(Timeline(), prepared, labels)
    assert _ratio(result.mild_missed) == (1, 1)
    [missed] = [f for f in result.failures if f.metric == "mild_missed"]
    assert "食欲不振" in missed.item


def test_untagged_present_is_not_a_mild_target() -> None:
    prepared = _prepared({1: "下痢"})
    labels = [_label(11, [_lev("下痢", "diarrhea", "present", "下痢", 1)])]
    result = evaluate(Timeline(), prepared, labels)
    assert _ratio(result.mild_missed) == (0, 0)
    assert _ratio(result.negation_as_present) == (0, 0)


@pytest.mark.parametrize("status", ["present", "improving"])
def test_negation_predicted_as_symptom_is_counted(status: str) -> None:
    text = "吐き気はなかった"
    prepared = _prepared({1: text})
    labels = [_label(11, [_lev("悪心", "nausea_appetite", "absent", text, 1)])]
    predicted = Timeline(events=[_pev(1, "悪心", "nausea_appetite", status, text, 1)])
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.negation_as_present) == (1, 1)
    [failure] = result.failures
    assert failure.metric == "negation_as_present"
    assert failure.expected == "absent" and failure.predicted == status


def test_negation_with_duplicate_present_prediction_is_counted() -> None:
    # 同じ記録・同じ用語で absent と present の両方を予測 → absent が対応づいても誤り
    text = "吐き気はなかった"
    prepared = _prepared({1: text})
    labels = [_label(11, [_lev("悪心", "nausea_appetite", "absent", text, 1)])]
    predicted = Timeline(
        events=[
            _pev(1, "悪心", "nausea_appetite", "absent", text, 1),
            _pev(1, "悪心", "nausea_appetite", "present", text, 1),
        ]
    )
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.negation_as_present) == (1, 1)
    [failure] = [f for f in result.failures if f.metric == "negation_as_present"]
    assert "present" in failure.predicted


def test_negation_ignores_prediction_of_other_label_with_same_question_key() -> None:
    # 患者B seq2 と同じ形の正しい予測: 食欲不振 present と 悪心 absent（同じ key）
    text = "なんとなく食欲がない。吐き気はない。"
    prepared = _prepared({1: text})
    labels = [_label(11, B_SEQ2_EVENTS, tags=["negation"])]
    predicted = Timeline(
        events=[
            _pev(
                1, "食欲不振", "nausea_appetite", "present", "なんとなく食欲がない", 1
            ),
            _pev(1, "悪心", "nausea_appetite", "absent", "吐き気はない", 1),
        ]
    )
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.negation_as_present) == (0, 1)
    assert result.failures == []


def test_negation_kept_absent_is_not_an_error() -> None:
    text = "吐き気はなかった"
    prepared = _prepared({1: text})
    labels = [_label(11, [_lev("悪心", "nausea_appetite", "absent", text, 1)])]
    predicted = Timeline(events=[_pev(1, "悪心", "nausea_appetite", "absent", text, 1)])
    result = evaluate(predicted, prepared, labels)
    assert _ratio(result.negation_as_present) == (0, 1)
    assert result.failures == []


# ---------------------------------------------------------------------------
# ⑤ 引用
# ---------------------------------------------------------------------------


def test_fabricated_quote_is_counted() -> None:
    prepared = _prepared({1: TEXT1})
    predicted = Timeline(
        events=[
            _pev(1, "下痢", "diarrhea", "present", "下痢が3回", 1),
            _pev(1, "悪心", "nausea_appetite", "absent", "吐き気はまったくない", 1),
        ],
        contradictions=[_pcon(1, "diarrhea", "none", "ひどい下痢", 1)],
    )
    result = evaluate(predicted, prepared, _basic_labels())
    assert _ratio(result.quote) == (1, 2)  # 出来事の source_quote だけ
    assert _ratio(result.contradiction_quote) == (0, 1)
    [quote_failure] = [f for f in result.failures if f.metric == "quote"]
    assert quote_failure.predicted == "吐き気はまったくない"
    assert quote_failure.entry_seq == 11
    [con_failure] = [f for f in result.failures if f.metric == "contradiction_quote"]
    assert con_failure.predicted == "ひどい下痢"


def test_unknown_entry_no_is_a_quote_failure_and_spurious_contradiction() -> None:
    prepared = _prepared({1: TEXT1})
    predicted = Timeline(
        events=[_pev(9, "下痢", "diarrhea", "present", "下痢が3回", 1)],
        contradictions=[_pcon(9, "diarrhea", "none", "下痢が3回", 1)],
    )
    result = evaluate(predicted, prepared, _basic_labels())
    assert _ratio(result.quote) == (0, 1)
    assert _ratio(result.contradiction_quote) == (0, 1)
    assert _ratio(result.contradiction_precision) == (0, 1)
    unknown = [
        f for f in result.failures if f.metric in ("quote", "contradiction_quote")
    ]
    assert len(unknown) == 2 and all(f.entry_seq is None for f in unknown)
    assert all("9" in f.item for f in unknown)


# ---------------------------------------------------------------------------
# 除外
# ---------------------------------------------------------------------------


def test_expect_unprocessed_entry_is_excluded() -> None:
    prepared = _prepared({1: TEXT1, 2: "磯鷲さんにもらった漢方"})
    labels = _basic_labels() + [_label(12, unprocessed=True)]
    predicted = Timeline(
        events=[
            _pev(1, "下痢", "diarrhea", "present", "下痢が3回", 1),
            _pev(1, "悪心", "nausea_appetite", "absent", "吐き気はなかった", 1),
            _pev(2, "腹痛", None, "present", "捏造の引用", 2),
        ],
        contradictions=[
            _pcon(1, "diarrhea", "none", "下痢が3回", 1),
            _pcon(2, "diarrhea", "none", "捏造の引用", 2),
        ],
    )
    result = evaluate(predicted, prepared, labels)
    assert result.leaked_unprocessed == 1  # 送信対象外のはずが入力に入った
    assert result.held_out_entries == 0
    assert result.entries_evaluated == 1
    assert _ratio(result.quote) == (2, 2)
    assert _ratio(result.contradiction_quote) == (1, 1)
    assert _ratio(result.contradiction_precision) == (1, 1)
    assert result.failures == []


def test_label_for_entry_outside_input_is_excluded() -> None:
    prepared = _prepared({1: TEXT1})
    labels = _basic_labels() + [
        _label(99, [_lev("下痢", "diarrhea", "present", "別コースの記録", 1)])
    ]
    result = evaluate(Timeline(), prepared, labels)
    assert result.label_events == 2
    assert _ratio(result.term) == (0, 2)


def test_entry_in_input_without_label_counts_predictions() -> None:
    prepared = _prepared({1: TEXT1, 2: "回答だけの記録"})
    predicted = Timeline(
        events=[_pev(2, "下痢", "diarrhea", "present", "回答だけの記録", 2)],
        contradictions=[_pcon(2, "diarrhea", "none", "回答だけの記録", 2)],
    )
    result = evaluate(predicted, prepared, _basic_labels())
    assert result.entries_evaluated == 2
    assert _ratio(result.quote) == (1, 1)
    assert _ratio(result.contradiction_quote) == (1, 1)
    assert _ratio(result.contradiction_precision) == (0, 1)


def test_held_out_entries_and_their_label_events_are_reported() -> None:
    # 二次検出で外した記録（prepared.unprocessed）のラベルは分母から外れる。件数は残す
    prepared = _prepared(
        {1: TEXT1},
        unprocessed=(UnprocessedEntry(entry_id=12, reason="unknown_before_honorific"),),
    )
    labels = _basic_labels() + [
        _label(
            12,
            [
                _lev("下痢", "diarrhea", "present", "下痢", 2),
                _lev("悪心", "nausea_appetite", "absent", "吐き気なし", 2),
            ],
        ),
        _label(13, unprocessed=True),
    ]
    result = evaluate(Timeline(), prepared, labels)
    assert result.held_out_entries == 1
    assert result.held_out_label_events == 2
    assert result.leaked_unprocessed == 0
    assert result.label_events == 2


def test_evaluate_rejects_duplicate_labels_for_one_entry() -> None:
    prepared = _prepared({1: TEXT1})
    with pytest.raises(ValueError):
        evaluate(Timeline(), prepared, _basic_labels() + _basic_labels())


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def test_aggregate_sums_numerators_and_denominators() -> None:
    prepared = _prepared({1: TEXT1})
    perfect = Timeline(
        events=[
            _pev(1, "下痢", "diarrhea", "present", "下痢が3回", 1),
            _pev(1, "悪心", "nausea_appetite", "absent", "吐き気はなかった", 1),
        ],
        contradictions=[_pcon(1, "diarrhea", "none", "下痢が3回", 1)],
    )
    a = evaluate(perfect, prepared, _basic_labels(), patient_id="P-A")
    b = evaluate(Timeline(), prepared, _basic_labels(), patient_id="P-B")
    total = aggregate([a, b])
    assert total.patient_id is None and total.course_no is None
    assert _ratio(total.term) == (2, 4)
    assert _ratio(total.date) == (2, 4)
    assert _ratio(total.date_paired) == (2, 2)
    assert _ratio(total.matched) == (2, 4)
    assert _ratio(total.contradiction_recall) == (1, 2)
    assert _ratio(total.contradiction_precision) == (1, 1)
    assert _ratio(total.quote) == (2, 2)
    assert _ratio(total.contradiction_quote) == (1, 1)
    assert total.label_events == 4
    assert total.entries_evaluated == 2
    assert len(total.failures) == len(b.failures)
    assert {f.patient_id for f in total.failures} == {"P-B"}


def test_aggregate_of_nothing_is_empty() -> None:
    total = aggregate([])
    assert total.label_events == 0
    assert total.term.rate is None
