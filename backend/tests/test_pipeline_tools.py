"""tsutae.pipeline.tools（emit_timeline / emit_report の受け口と RunCollector）。"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from pipeline_fakes import label_payloads, prepare_case

from tsutae.pipeline.logs import MemoryLogger
from tsutae.pipeline.tools import (
    EMIT_REPORT,
    EMIT_REPORT_SCHEMA,
    EMIT_TIMELINE,
    EMIT_TIMELINE_SCHEMA,
    SERVER_NAME,
    RunCollector,
    build_server,
    build_tools,
    handle_emit_report,
    handle_emit_timeline,
)
from tsutae.schemas import Contradiction, ReportPicks, SymptomSummary, TimelineEvent
from tsutae.synthetic import load_terms

PREPARED = prepare_case("demo_patient")
TIMELINE, REPORT = label_payloads("demo_patient", PREPARED)
LAST_NO = max(PREPARED.masked_texts)  # 「…きょうは吐き気も下痢もなかった」
_NO_BY_ID = {i: n for n, i in PREPARED.entry_ids.items()}
PROXY_NO = _NO_BY_ID[33]  # 代理入力。下痢 none ＋「夕方から下痢が3回あった」（Day5）
HICCUP_NO = _NO_BY_ID[
    28
]  # 自由記載だけ（クローズ回答なし）「朝からしゃっくりがとまらない」
FORBIDDEN = (
    "Grade",
    "グレード",
    "軽症",
    "中等症",
    "重症",
    "重篤",
    "軽度",
    "高度",
    "受診",
)


def _event(**over: Any) -> dict[str, Any]:
    base = {
        "entry_no": LAST_NO,
        "date": "2026-11-08",
        "day": 13,
        "course_no": 3,
        "term": "下痢",
        "question_key": "diarrhea",
        "status": "absent",
        "source_quote": "吐き気も下痢もなかった",
        "confidence": 0.9,
        "recalled": False,
        "by_proxy": False,
    }
    return {**base, **over}


def _contradiction(**over: Any) -> dict[str, Any]:
    base = {
        "entry_no": PROXY_NO,
        "date": "2026-10-31",
        "day": 5,
        "question_key": "diarrhea",
        "closed_answer": "none",
        "free_text_quote": "夕方から下痢が3回あった",
    }
    return {**base, **over}


def _summary(**over: Any) -> dict[str, Any]:
    # 口腔粘膜炎の最初の出来事は Day7 の記録の回想（おとといの夜 = 10/31、Day5）
    base = {
        "term": "口腔粘膜炎",
        "question_key": "stomatitis",
        "start_day": 5,
        "start_date": "2026-10-31",
        "representative_quote": "おとといの夜から口内炎がいたい",
        "confidence": 0.9,
    }
    return {**base, **over}


# 口腔粘膜炎だけが present / improving の timeline（per_symptom は _summary() の1行で足りる）
STOMATITIS_TIMELINE = {
    "events": [
        e
        for e in TIMELINE["events"]
        if e["term"] == "口腔粘膜炎" or e["status"] == "absent"
    ],
    "contradictions": [],
}


def _collector(logger: MemoryLogger | None = None) -> RunCollector:
    return RunCollector.from_prepared(PREPARED, logger=logger)


def _with_timeline(
    logger: MemoryLogger | None = None, timeline: dict[str, Any] | None = None
) -> RunCollector:
    collector = _collector(logger)
    payload = STOMATITIS_TIMELINE if timeline is None else timeline
    assert not handle_emit_timeline(payload, collector).get("is_error")
    return collector


def _text(result: dict[str, Any]) -> str:
    return "".join(c["text"] for c in result["content"])


def test_valid_timeline_is_stored() -> None:
    collector = _collector()
    result = handle_emit_timeline(
        {"events": [_event()], "contradictions": [_contradiction()]}, collector
    )
    assert not result.get("is_error")
    assert collector.timeline is not None
    assert collector.timeline.events == [TimelineEvent.model_validate(_event())]
    assert collector.timeline.contradictions == [
        Contradiction.model_validate(_contradiction())
    ]
    assert collector.timeline.unprocessed_entries == []


def test_contradictions_may_be_omitted() -> None:
    collector = _collector()
    result = handle_emit_timeline({"events": []}, collector)
    assert not result.get("is_error")
    assert collector.timeline is not None and collector.timeline.events == []


@pytest.mark.parametrize(
    ("event", "where"),
    [
        (
            {k: v for k, v in _event().items() if k != "source_quote"},
            "events.0.source_quote",
        ),
        (_event(grade=2), "events.0.grade"),
        (_event(status="mild"), "events.0.status"),
        (_event(confidence=1.5), "events.0.confidence"),
        (_event(date="昨日"), "events.0.date"),
    ],
)
def test_invalid_timeline_is_error_with_item_name(event: dict, where: str) -> None:
    collector = _collector()
    result = handle_emit_timeline({"events": [event]}, collector)
    assert result["is_error"] is True
    assert where in _text(result)
    assert collector.timeline is None


def test_unknown_entry_no_is_error() -> None:
    collector = _collector()
    result = handle_emit_timeline(
        {
            "events": [_event(), _event(entry_no=999)],
            "contradictions": [_contradiction(entry_no=998)],
        },
        collector,
    )
    assert result["is_error"] is True
    text = _text(result)
    assert "events.1.entry_no" in text and "contradictions.0.entry_no" in text
    assert collector.timeline is None


def test_error_text_does_not_echo_input_values() -> None:
    collector = _collector()
    bad = _event(source_quote="捏造された引用の文", date="きのうのこと")
    result = handle_emit_timeline({"events": [bad]}, collector)
    assert result["is_error"] is True
    assert "捏造" not in _text(result) and "きのう" not in _text(result)


def test_non_object_args_are_error() -> None:
    collector = _collector()
    assert handle_emit_timeline(["events"], collector)["is_error"] is True  # type: ignore[arg-type]
    assert handle_emit_report("x", collector)["is_error"] is True  # type: ignore[arg-type]


def test_last_valid_timeline_wins() -> None:
    collector = _collector()
    handle_emit_timeline({"events": [_event()]}, collector)
    handle_emit_timeline(
        {"events": [_event(term="悪心", question_key="nausea_appetite")]}, collector
    )
    handle_emit_timeline(
        {"events": [_event(status="bad")]}, collector
    )  # 失敗は採用しない
    assert collector.timeline is not None
    assert [e.term for e in collector.timeline.events] == ["悪心"]
    assert collector.timeline_calls == 3


def test_valid_report_is_stored_and_last_wins() -> None:
    collector = _with_timeline()
    assert not handle_emit_report({"per_symptom": [_summary()]}, collector).get(
        "is_error"
    )
    later = _summary(representative_quote="口内炎はまだすこしいたい")
    assert not handle_emit_report({"per_symptom": [later]}, collector).get("is_error")
    assert collector.picks == ReportPicks(
        per_symptom=[SymptomSummary.model_validate(later)]
    )
    assert collector.report_calls == 2


def test_empty_report_is_rejected_when_events_have_symptoms() -> None:
    # 症状の出来事があるのに per_symptom が空 = AI が症状を黙って省いた（Skill §4）
    collector = _with_timeline()
    handle_emit_report({"per_symptom": [_summary()]}, collector)
    result = handle_emit_report({"per_symptom": []}, collector)
    assert result["is_error"] is True
    assert "行が無い" in _text(result)
    assert collector.picks == ReportPicks(
        per_symptom=[SymptomSummary.model_validate(_summary())]
    )


def test_empty_report_is_accepted_when_no_event_has_a_symptom() -> None:
    collector = _collector()
    assert not handle_emit_timeline({"events": [_event()]}, collector).get("is_error")
    assert not handle_emit_report({"per_symptom": []}, collector).get("is_error")
    assert collector.picks == ReportPicks(per_symptom=[])


def test_label_report_rows_must_all_be_there_in_order() -> None:
    collector = _with_timeline(timeline=TIMELINE)
    rows = REPORT["per_symptom"]
    assert len(rows) >= 3
    missing = handle_emit_report({"per_symptom": rows[:-1]}, collector)
    assert missing["is_error"] is True and "行が無い" in _text(missing)
    assert collector.picks is None
    assert not handle_emit_report(REPORT, collector).get("is_error")


def test_report_rows_in_any_order_are_accepted_and_sorted() -> None:
    # 「同じ日なら term 名順」は文字列の順でモデルが再現しにくい。拒否せず並べ直す
    collector = _with_timeline(timeline=TIMELINE)
    rows = REPORT["per_symptom"]
    result = handle_emit_report({"per_symptom": rows[::-1]}, collector)
    assert not result.get("is_error")
    assert collector.picks == ReportPicks.model_validate(REPORT)
    keys = [(s.start_date, s.term) for s in collector.picks.per_symptom]
    assert keys == sorted(keys)


def test_error_says_nothing_was_accepted_and_to_resend_everything() -> None:
    collector = _collector()
    result = handle_emit_timeline({"events": [_event(day=99)]}, collector)
    text = _text(result)
    assert "受け付けていない" in text
    assert "全体" in text


def test_error_lists_up_to_twenty_reasons() -> None:
    collector = _collector()
    events = [_event(day=99, source_quote=f"{i}") for i in range(25)]
    text = _text(handle_emit_timeline({"events": events}, collector))
    assert "events.19.day" in text
    assert "events.20.day" not in text
    assert "ほか 5 件" in text


def test_schema_fields_carry_descriptions_for_the_model() -> None:
    from tsutae.pipeline.tools import EmitReportArgs, EmitTimelineArgs

    defs = EMIT_TIMELINE_SCHEMA["$defs"]
    event = defs["TimelineEvent"]["properties"]
    assert "対応表" in event["day"]["description"]
    assert "部分文字列" in event["source_quote"]["description"]
    assert "description" in defs["Contradiction"]["properties"]["closed_answer"]
    summary = EMIT_REPORT_SCHEMA["$defs"]["SymptomSummary"]["properties"]
    assert "source_quote" in summary["representative_quote"]["description"]
    # 元の pydantic の schema は書き換えない（複製に足す）
    plain = EmitTimelineArgs.model_json_schema()["$defs"]["TimelineEvent"]
    assert "description" not in plain["properties"]["day"]
    assert "description" not in (
        EmitReportArgs.model_json_schema()["$defs"]["SymptomSummary"]["properties"][
            "start_day"
        ]
    )


def test_invalid_report_is_error_with_item_name() -> None:
    collector = _with_timeline()
    result = handle_emit_report({"per_symptom": [_summary(confidence=2)]}, collector)
    assert result["is_error"] is True
    assert "per_symptom.0.confidence" in _text(result)
    assert collector.picks is None


def test_collector_logs_accept_and_reject_without_text() -> None:
    logger = MemoryLogger()
    collector = _collector(logger)
    handle_emit_timeline({"events": [_event(status="bad")]}, collector)
    handle_emit_timeline(TIMELINE, collector)
    handle_emit_report(REPORT, collector)
    timeline_logs = logger.find("emit_timeline")
    assert [r["decision"] for r in timeline_logs] == [
        "reject:events.0.status",
        "accept",
    ]
    assert logger.find("emit_report")[0]["decision"] == "accept"


def test_collector_knows_entry_numbers() -> None:
    collector = _collector()
    assert collector.entry_nos == frozenset(PREPARED.entry_ids)


def test_input_schemas_are_json_schema_from_pydantic() -> None:
    payload = {"events": [_event()], "contradictions": [_contradiction()]}
    jsonschema.validate(instance=payload, schema=EMIT_TIMELINE_SCHEMA)
    jsonschema.validate(
        instance={"per_symptom": [_summary()]}, schema=EMIT_REPORT_SCHEMA
    )
    assert EMIT_TIMELINE_SCHEMA["type"] == "object"
    assert "events" in EMIT_TIMELINE_SCHEMA["required"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"contradictions": []}, schema=EMIT_TIMELINE_SCHEMA
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"events": [_event(extra=1)]}, schema=EMIT_TIMELINE_SCHEMA
        )


async def test_build_tools_wires_handlers_to_collector() -> None:
    collector = _collector()
    tools = build_tools(collector)
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {EMIT_TIMELINE, EMIT_REPORT}
    assert by_name[EMIT_TIMELINE].input_schema == EMIT_TIMELINE_SCHEMA
    assert by_name[EMIT_REPORT].input_schema == EMIT_REPORT_SCHEMA
    await by_name[EMIT_TIMELINE].handler(TIMELINE)
    await by_name[EMIT_REPORT].handler(REPORT)
    assert collector.timeline is not None
    assert collector.picks == ReportPicks.model_validate(REPORT)


def test_build_server_is_named_tsutae() -> None:
    server = build_server(_collector())
    assert server["type"] == "sdk"
    assert server["name"] == SERVER_NAME == "tsutae"
    assert server["instance"] is not None


# --- 用語・question_key（一覧から選ぶ項目）-----------------------------------


@pytest.mark.parametrize(
    "term",
    [
        "重症の下痢（Grade 3）",
        "Grade 2 下痢",
        "重篤な発熱。すぐ受診を",
        "下痢（軽度）",
        "げり",
        "Diarrhea",
    ],
)
def test_term_outside_the_ctcae_list_is_rejected(term: str) -> None:
    collector = _collector()
    result = handle_emit_timeline({"events": [_event(term=term)]}, collector)
    assert result["is_error"] is True
    assert "events.0.term" in _text(result)
    assert term not in _text(result)  # 入力の文面は返さない
    assert collector.timeline is None


def test_term_list_itself_has_no_severity_or_advice_words() -> None:
    for item in load_terms():
        assert not any(word in item["term"] for word in FORBIDDEN), item["term"]


@pytest.mark.parametrize(
    ("term", "question_key"),
    [
        ("下痢", "fever"),
        ("下痢", None),
        ("下痢", "made_up_key"),
        ("しゃっくり", "diarrhea"),
        ("手掌・足底発赤知覚不全症候群", "hand_foot"),  # FOLFOX の質問に無い
    ],
)
def test_question_key_must_follow_the_term(term: str, question_key: Any) -> None:
    collector = _collector()
    event = _event(term=term, question_key=question_key)
    result = handle_emit_timeline({"events": [event]}, collector)
    assert result["is_error"] is True
    assert "events.0.question_key" in _text(result)


def test_term_without_a_question_this_time_takes_null() -> None:
    collector = _collector()
    event = _event(term="手掌・足底発赤知覚不全症候群", question_key=None)
    assert not handle_emit_timeline({"events": [event]}, collector).get("is_error")


# --- 入力から写す項目（course_no・by_proxy・date と day・recalled）---------------


@pytest.mark.parametrize(
    ("over", "where"),
    [
        ({"course_no": 7}, "events.0.course_no"),
        ({"by_proxy": True}, "events.0.by_proxy"),
        ({"day": 99}, "events.0.day"),
        ({"day": None}, "events.0.day"),
        ({"date": "2027-01-01"}, "events.0.date"),  # 記録日より後
        ({"date": "2026-11-06", "day": 11}, "events.0.recalled"),
        ({"recalled": True}, "events.0.recalled"),
        ({"date": "2026-10-20", "day": -6, "recalled": True}, "events.0.day"),
    ],
)
def test_copied_event_fields_must_match_the_input(over: dict, where: str) -> None:
    collector = _collector()
    result = handle_emit_timeline({"events": [_event(**over)]}, collector)
    assert result["is_error"] is True
    assert where in _text(result)
    assert collector.timeline is None


def test_proxy_entry_events_must_say_by_proxy() -> None:
    collector = _collector()
    event = _event(
        entry_no=PROXY_NO,
        date="2026-10-31",
        day=5,
        status="present",
        source_quote="夕方から下痢が3回あった",
    )
    assert handle_emit_timeline({"events": [event]}, collector)["is_error"] is True
    ok = {**event, "by_proxy": True}
    assert not handle_emit_timeline({"events": [ok]}, collector).get("is_error")


def test_recalled_event_before_day1_has_null_day() -> None:
    collector = _collector()
    event = _event(date="2026-10-20", day=None, recalled=True)
    assert not handle_emit_timeline({"events": [event]}, collector).get("is_error")


# --- 食い違い（クローズ回答を書き換えない）---------------------------------------


@pytest.mark.parametrize(
    ("over", "where"),
    [
        ({"closed_answer": "hard"}, "contradictions.0.closed_answer"),
        ({"closed_answer": "present"}, "contradictions.0.closed_answer"),
        (
            {"question_key": "fever", "closed_answer": "measured"},
            "contradictions.0.closed_answer",
        ),
        ({"day": 12}, "contradictions.0.day"),
        ({"date": "2026-12-31"}, "contradictions.0.date"),
        ({"question_key": "hand_foot"}, "contradictions.0.question_key"),
        (
            {
                "entry_no": HICCUP_NO,
                "date": "2026-10-28",
                "day": 2,
                "question_key": "fever",
                "closed_answer": "measured",
                "free_text_quote": "しゃっくり",
            },
            "contradictions.0.question_key",
        ),
    ],
)
def test_contradiction_must_copy_the_closed_answer(over: dict, where: str) -> None:
    collector = _collector()
    payload = {"events": [], "contradictions": [_contradiction(**over)]}
    result = handle_emit_timeline(payload, collector)
    assert result["is_error"] is True
    assert where in _text(result)
    assert collector.timeline is None


# --- 症状別の時系列（受け付けた events に結び付ける）--------------------------------


def test_report_before_any_timeline_is_rejected() -> None:
    collector = _collector()
    result = handle_emit_report({"per_symptom": [_summary()]}, collector)
    assert result["is_error"] is True
    assert "emit_timeline" in _text(result)
    assert collector.picks is None


def test_label_report_links_to_label_timeline() -> None:
    collector = _with_timeline(timeline=TIMELINE)
    assert not handle_emit_report(REPORT, collector).get("is_error")


def test_representative_quote_may_come_from_a_later_event_of_the_term() -> None:
    # 代表引用は「その症状をよく表す出来事」の1つ。開始日は最初の出来事のまま
    collector = _with_timeline()
    later = _summary(representative_quote="口内炎はまだすこしいたい")
    assert not handle_emit_report({"per_symptom": [later]}, collector).get("is_error")


@pytest.mark.parametrize(
    ("over", "where"),
    [
        ({"term": "重篤な発熱。すぐ受診を"}, "per_symptom.0.term"),
        ({"term": "嘔吐"}, "per_symptom.0.term"),  # 出来事に無い用語
        ({"question_key": None}, "per_symptom.0.question_key"),
        ({"start_date": "2026-11-05", "start_day": 10}, "per_symptom.0.start_date"),
        ({"start_day": 7}, "per_symptom.0.start_day"),
        (
            {"representative_quote": "夕方から下痢が3回あった"},
            "per_symptom.0.representative_quote",
        ),
        ({"representative_quote": "口内炎"}, "per_symptom.0.representative_quote"),
        ({"confidence": 1.0}, "per_symptom.0.confidence"),
    ],
)
def test_summary_must_match_accepted_events(over: dict, where: str) -> None:
    collector = _with_timeline()
    result = handle_emit_report({"per_symptom": [_summary(**over)]}, collector)
    assert result["is_error"] is True
    assert where in _text(result)
    assert "重篤" not in _text(result)
    assert collector.picks is None


def test_term_with_only_absent_events_is_not_a_summary() -> None:
    collector = _collector()
    assert not handle_emit_timeline({"events": [_event()]}, collector).get("is_error")
    absent_only = _summary(
        term="下痢",
        question_key="diarrhea",
        start_day=13,
        start_date="2026-11-08",
        representative_quote="吐き気も下痢もなかった",
    )
    result = handle_emit_report({"per_symptom": [absent_only]}, collector)
    assert result["is_error"] is True and "per_symptom.0.term" in _text(result)


def test_same_term_twice_is_rejected() -> None:
    collector = _with_timeline()
    result = handle_emit_report({"per_symptom": [_summary(), _summary()]}, collector)
    assert result["is_error"] is True and "per_symptom.1.term" in _text(result)


def test_new_timeline_drops_picks_that_no_longer_link() -> None:
    logger = MemoryLogger()
    collector = _with_timeline(logger)
    handle_emit_report({"per_symptom": [_summary()]}, collector)
    assert collector.picks is not None
    handle_emit_timeline(STOMATITIS_TIMELINE, collector)  # 同じ内容なら残す
    assert collector.picks is not None
    result = handle_emit_timeline({"events": [_event()]}, collector)
    assert not result.get("is_error")
    assert collector.picks is None
    assert "emit_report" in _text(result)
    assert logger.find("emit_report")[-1]["decision"] == "drop:stale"
