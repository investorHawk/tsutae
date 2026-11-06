"""tsutae.report.render_report_html（A4 一枚の HTML）。"""

from __future__ import annotations

import re
from datetime import date

import pytest

from tsutae.report import build_report_data, render_report_html
from tsutae.report.sample import SampleInputs, load_demo_inputs
from tsutae.schemas import Question, QuoteItem, ReportData, SymptomSummary

BANNED = ("Grade", "グレード", "軽症", "中等症", "重症", "重篤")


def _data(sample: SampleInputs) -> ReportData:
    return build_report_data(**sample.build_kwargs())


def _html(
    sample: SampleInputs, data: ReportData | None = None, **kwargs: object
) -> str:
    return render_report_html(
        data or _data(sample), questions=list(sample.regimen_skill.questions), **kwargs
    )


def _cell_html(html: str, row: str, day: int) -> str:
    match = re.search(
        rf'<td class="([^"]*)" data-row="{row}" data-day="{day}">(.*?)</td>', html, re.S
    )
    assert match, (row, day)
    return match.group(1) + "|" + match.group(2)


@pytest.fixture(scope="module")
def demo() -> SampleInputs:
    return load_demo_inputs()


@pytest.fixture(scope="module")
def demo_html(demo: SampleInputs) -> str:
    return _html(demo)


@pytest.fixture(scope="module")
def fallback_html() -> str:
    return _html(load_demo_inputs(fallback=True))


# ---------------------------------------------------------------------------
# 出さない語・欄外の固定文言
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["demo", "fallback"])
def test_no_severity_words(which: str, demo_html: str, fallback_html: str) -> None:
    html = demo_html if which == "demo" else fallback_html
    for word in BANNED:
        assert word not in html, word
    assert "grade" not in html.lower()


def test_synthetic_banner_and_sources(demo_html: str, fallback_html: str) -> None:
    for html in (demo_html, fallback_html):
        assert "症例は全て合成" in html
        assert (
            "用語名はこのアプリの用語の一覧から AI が当てはめた候補で、医師が確定する。"
            in html
        )
        assert "凡例" in html


def test_legend_is_fixed_text(demo_html: str, fallback_html: str) -> None:
    def legend(html: str) -> str:
        match = re.search(r'<div class="legend">(.*?)</div>', html, re.S)
        assert match
        return match.group(1)

    text = legend(demo_html)
    assert legend(fallback_html) == text
    for word in (
        "なし",
        "ある",
        "つらい",
        "入力なし",
        "未設問",
        "つらくて書けない",
        "○",
        "回",
        "代",
    ):
        assert word in text, word


def test_css_is_embedded(demo_html: str) -> None:
    assert "<link" not in demo_html
    style = re.search(r"<style>(.*?)</style>", demo_html, re.S)
    assert style
    css = style.group(1)
    assert "@page" in css and "size: A4" in css and "@media print" in css
    assert "linear-gradient" in css
    assert "print-color-adjust: exact" in css
    assert "&gt;" not in css and "&#34;" not in css  # CSS はエスケープしない


# ---------------------------------------------------------------------------
# フォールバック
# ---------------------------------------------------------------------------


def test_fallback_label(demo_html: str, fallback_html: str) -> None:
    assert "AI変換なし" in fallback_html
    assert 'class="fallback-notice"' in fallback_html
    assert "AI変換なし" not in demo_html
    table = re.search(r'<table class="grid">(.*?)</table>', fallback_html, re.S)
    assert table and 'class="mark"' not in table.group(1) and "○" not in table.group(1)


# ---------------------------------------------------------------------------
# エスケープ
# ---------------------------------------------------------------------------


def test_free_text_is_escaped(demo: SampleInputs) -> None:
    data = _data(demo)
    evil = "<script>alert('x')</script>"
    quotes = [QuoteItem(entry_no=99, day=6, date=date(2026, 11, 1), text=evil)]
    per_symptom = [
        SymptomSummary(
            term="<b>下痢</b>",
            start_day=5,
            start_date=date(2026, 10, 31),
            representative_quote=evil,
            confidence=0.9,
        )
    ]
    tampered = data.model_copy(update={"quotes": quotes, "per_symptom": per_symptom})
    html = _html(demo, tampered)
    assert "<script" not in html
    assert "&lt;script&gt;" in html
    assert "<b>下痢</b>" not in html and "&lt;b&gt;" in html


def test_question_text_is_escaped(demo: SampleInputs) -> None:
    questions = [
        Question(key="meal_intake", text="<i>食事</i>", answer_type="three_level")
    ]
    data = _data(demo)
    attention = [
        (
            a.model_copy(update={"question_key": "meal_intake"})
            if a.kind == "contradiction"
            else a
        )
        for a in data.attention
    ]
    html = render_report_html(
        data.model_copy(update={"attention": attention}), questions=questions
    )
    assert "<i>食事</i>" not in html and "&lt;i&gt;食事&lt;/i&gt;" in html


# ---------------------------------------------------------------------------
# 要確認・経過表（デモ患者 C3）
# ---------------------------------------------------------------------------


def test_attention_order(demo_html: str) -> None:
    section = re.search(r'<section class="attention">(.*?)</section>', demo_html, re.S)
    assert section
    text = section.group(1)
    positions = [
        text.index(w)
        for w in ("食い違い", "発熱", "つらくて書けない", "未処理の記載あり")
    ]
    assert positions == sorted(positions)
    assert "37.9℃" in text
    assert "夕方から下痢が3回あった" in text
    assert "前コースも同じ Day" in text


def test_too_sick_columns_are_slashed(demo_html: str) -> None:
    slashed = sorted(
        {
            int(d)
            for d in re.findall(
                r'<th class="[^"]*\bslash\b[^"]*" data-day="(\d+)"', demo_html
            )
        }
    )
    assert slashed == [3, 4, 5]
    for day in (3, 4, 5):
        assert "slash" in _cell_html(demo_html, "c3-diarrhea", day).split("|")[0]
    assert "slash" not in _cell_html(demo_html, "c3-diarrhea", 6).split("|")[0]


def test_day5_contradiction_visible(demo_html: str) -> None:
    cls, body = _cell_html(demo_html, "c3-diarrhea", 5).split("|", 1)
    assert "st-none" in cls
    assert "−" in body and "○" in body


def test_day8_temperature(demo_html: str) -> None:
    _, body = _cell_html(demo_html, "c3-temperature", 8).split("|", 1)
    assert "37.9" in body


def test_proxy_and_recalled_marks(demo_html: str) -> None:
    head = re.search(r'<th class="[^"]*" data-day="5">(.*?)</th>', demo_html, re.S)
    assert head and "代" in head.group(1)
    head6 = re.search(r'<th class="[^"]*" data-day="6">(.*?)</th>', demo_html, re.S)
    assert head6 and "代" not in head6.group(1)
    _, body = _cell_html(demo_html, "c3-stomatitis", 5).split("|", 1)
    assert "○" in body and "回" in body


def test_cell_states_render(demo_html: str) -> None:
    cls, body = _cell_html(demo_html, "c3-numbness", 9).split("|", 1)
    assert "st-no_input" in cls and body.strip() == ""
    cls, _ = _cell_html(demo_html, "c3-nausea_appetite", 5).split("|", 1)
    assert "st-hard" in cls
    cls, _ = _cell_html(demo_html, "c3-numbness", 2).split("|", 1)
    assert "st-present" in cls
    cls, _ = _cell_html(demo_html, "c2-numbness", 3).split("|", 1)
    assert "st-too_sick" in cls and "slash" in cls
    assert "クローズ回答のみ" in demo_html


def test_not_asked_renders_double_dash(demo: SampleInputs) -> None:
    old = "regimen-folfox@0"
    entries = [
        (
            e.model_copy(
                update={
                    "skill_version": old,
                    "answers": [a for a in e.answers if a.question_key != "stomatitis"],
                }
            )
            if e.record_date == date(2026, 10, 27)
            else e
        )
        for e in demo.entries
    ]
    questions = [q for q in demo.regimen_skill.questions if q.key != "stomatitis"]
    kwargs = {
        **demo.with_entries(entries).build_kwargs(),
        "questions_by_version": {**demo.questions_by_version, old: questions},
    }
    html = _html(demo, build_report_data(**kwargs))
    cls, body = _cell_html(html, "c3-stomatitis", 1).split("|", 1)
    assert "st-not_asked" in cls and "−−" in body


# ---------------------------------------------------------------------------
# 症状別・引用・欄の並び
# ---------------------------------------------------------------------------


def test_low_confidence_mark(demo: SampleInputs) -> None:
    data = _data(demo)
    per_symptom = [
        SymptomSummary(
            term="倦怠感",
            start_day=2,
            start_date=date(2026, 10, 28),
            representative_quote="だるい",
            confidence=0.3,
        ),
        SymptomSummary(
            term="下痢",
            start_day=5,
            start_date=date(2026, 10, 31),
            representative_quote="下痢",
            confidence=0.9,
        ),
    ]
    html = _html(demo, data.model_copy(update={"per_symptom": per_symptom}))
    section = re.search(r'<section class="per-symptom">(.*?)</section>', html, re.S)
    assert section
    rows = re.findall(r"<tr>(.*?)</tr>", section.group(1), re.S)
    low = next(r for r in rows if "倦怠感" in r)
    high = next(r for r in rows if "下痢" in r)
    assert "？" in low and "？" not in high
    html_strict = _html(
        demo,
        data.model_copy(update={"per_symptom": per_symptom}),
        low_confidence_threshold=0.95,
    )
    section = re.search(
        r'<section class="per-symptom">(.*?)</section>', html_strict, re.S
    )
    assert section and section.group(1).count("？") == 2


def test_sections_order_and_omission(demo: SampleInputs, demo_html: str) -> None:
    order = [m for m in re.findall(r'<section class="([a-z-]+)', demo_html)]
    assert order == ["header", "attention", "grid", "per-symptom", "quotes"]
    html = _html(demo, sections=["header", "grid", "attention"])
    order = re.findall(r'<section class="([a-z-]+)', html)
    assert order == ["header", "grid", "attention"]


def test_quotes_go_to_next_page_when_long(demo: SampleInputs, demo_html: str) -> None:
    assert "page-break" not in re.search(
        r'<section class="quotes[^"]*"', demo_html
    ).group(0)
    data = _data(demo)
    many = [
        QuoteItem(entry_no=i, day=1, date=date(2026, 10, 27), text="あ" * 80)
        for i in range(1, 31)
    ]
    html = _html(demo, data.model_copy(update={"quotes": many}))
    assert re.search(r'<section class="quotes page-break"', html)


def test_quotes_render_masked_text(demo: SampleInputs, demo_html: str) -> None:
    section = re.search(
        r'<section class="quotes[^"]*">(.*?)</section>', demo_html, re.S
    )
    assert section
    text = section.group(1)
    assert "○○先生" in text and "佐藤" not in text and "磯鷲" not in text
    assert "おとといの夜から口内炎がいたい" in text


def test_header_fields(demo_html: str) -> None:
    section = re.search(r'<section class="header">(.*?)</section>', demo_html, re.S)
    assert section
    text = section.group(1)
    for word in (
        "A-023",
        "P-DEMO0001",
        "FOLFOX",
        "第3コース",
        "11日/14日",
        "入力なし3",
        "つらくて書けない3",
    ):
        assert word in text, word


def test_render_is_deterministic(demo: SampleInputs) -> None:
    assert _html(demo) == _html(demo)


def test_delay_note_in_header() -> None:
    sample = load_demo_inputs(visit_date=date(2026, 10, 26))
    html = _html(sample)
    section = re.search(r'<section class="header">(.*?)</section>', html, re.S)
    assert section and "延期（予定より2日）" in section.group(1)
    assert "第2コース" in section.group(1)


def test_unknown_section_is_rejected(demo: SampleInputs) -> None:
    with pytest.raises(ValueError):
        _html(demo, sections=["header", "summary"])


# ---------------------------------------------------------------------------
# AI 由来の欄の文言・禁止語（レビュー指摘）
# ---------------------------------------------------------------------------


def _section(html: str, cls: str) -> str:
    match = re.search(rf'<section class="{cls}[^"]*">(.*?)</section>', html, re.S)
    assert match, cls
    return match.group(1)


def test_footer_names_all_ai_parts(demo_html: str, fallback_html: str) -> None:
    for html in (demo_html, fallback_html):
        footer = re.search(r'<footer class="notes">(.*?)</footer>', html, re.S)
        assert footer
        text = footer.group(1)
        assert "○・要確認の食い違い・症状別の時系列が AI の変換による" in text
        assert "○ と症状別の時系列だけ" not in text


@pytest.mark.parametrize("picks", ["none", "empty"])
def test_empty_per_symptom_does_not_claim_no_symptoms(
    demo: SampleInputs, picks: str
) -> None:
    from tsutae.schemas import ReportPicks

    value = None if picks == "none" else ReportPicks(per_symptom=[])
    result = demo.result.model_copy(update={"picks": value})
    data = build_report_data(**{**demo.build_kwargs(), "result": result})
    assert data.per_symptom == [] and data.fallback is False
    section = _section(_html(demo, data), "per-symptom")
    assert "載せる症状はない" not in section
    assert "症状が無いという意味ではない" in section


def test_empty_quotes_do_not_claim_no_free_text(demo: SampleInputs) -> None:
    skill = demo.report_skill.model_copy(update={"quotes_max_items": 0})
    data = build_report_data(**{**demo.build_kwargs(), "report_skill": skill})
    assert data.quotes == [] and demo.prepared.masked_texts
    section = _section(_html(demo, data), "quotes")
    assert "自由記載はない" not in section
    assert "上限" in section


@pytest.mark.parametrize("term", ["下痢 Grade 2", "下痢（重症）", "grade3 下痢"])
def test_render_refuses_severity_word_in_term(demo: SampleInputs, term: str) -> None:
    # build を通らずに改ざんされた ReportData でも、用語名の禁止語は紙に出さない
    data = _data(demo)
    per_symptom = [
        SymptomSummary(
            term=term,
            start_day=5,
            start_date=date(2026, 10, 31),
            representative_quote="夕方から下痢が3回あった",
            confidence=0.9,
        )
    ]
    with pytest.raises(ValueError):
        _html(demo, data.model_copy(update={"per_symptom": per_symptom}))


def test_previous_course_too_sick_is_slashed_with_free_text(demo: SampleInputs) -> None:
    from datetime import datetime

    from tsutae.config import JST
    from tsutae.schemas import Entry

    extra = Entry(
        id=901,
        patient_id=demo.patient_id,
        recorded_at=datetime(2026, 10, 17, 22, 0, tzinfo=JST),
        record_date=date(2026, 10, 17),
        kind="free_text",
        by_proxy=False,
        skill_version="regimen-folfox@1",
        free_text="ねむれない",
    )
    kwargs = {**demo.build_kwargs(), "entries": [*demo.entries, extra]}
    html = _html(demo, build_report_data(**kwargs))
    for row in ("c2-numbness", "c2-diarrhea", "c2-temperature"):
        cls = _cell_html(html, row, 5).split("|")[0]
        assert "st-too_sick" in cls and "slash" in cls, row


def test_reception_no_is_escaped(demo: SampleInputs) -> None:
    # 仮名ID は記録と一致しないと組み立てで止まる（test_report_validate.py）。受付番号は自由入力
    kwargs = {**demo.build_kwargs(), "reception_no": "<script>x</script>"}
    html = _html(demo, build_report_data(**kwargs))
    assert "<script>x" not in html and "&lt;script&gt;x" in html


# ---------------------------------------------------------------------------
# 引用の上限・前コースの斜線・未処理の理由
# ---------------------------------------------------------------------------


def test_quotes_cut_at_limit_say_so(demo: SampleInputs) -> None:
    # 自由記載 9 件のうち上限 3 件だけ載せたとき、省いた可能性を紙に書く
    skill = demo.report_skill.model_copy(update={"quotes_max_items": 3})
    data = build_report_data(**{**demo.build_kwargs(), "report_skill": skill})
    assert len(data.quotes) == 3
    section = _section(_html(demo, data, quotes_max_items=3), "quotes")
    assert "上限3件" in section and "省いた" in section


def test_quotes_under_limit_have_no_omission_note(demo: SampleInputs) -> None:
    data = _data(demo)
    assert len(data.quotes) < demo.report_skill.quotes_max_items
    section = _section(
        _html(demo, data, quotes_max_items=demo.report_skill.quotes_max_items),
        "quotes",
    )
    assert "省いた" not in section
    assert "省いた" not in _section(_html(demo, data), "quotes")


def _c2_entry(demo: SampleInputs, entry_id: int, **fields: object) -> object:
    from datetime import datetime

    from tsutae.config import JST
    from tsutae.schemas import Entry

    when = datetime(2026, 10, 17, 22, 0, tzinfo=JST)  # C2 Day5（too_sick の日）
    base: dict[str, object] = {
        "id": entry_id,
        "patient_id": demo.patient_id,
        "recorded_at": when,
        "record_date": when.date(),
        "kind": "answers",
        "by_proxy": False,
        "skill_version": "regimen-folfox@1",
    }
    return Entry(**{**base, **fields})


def test_previous_course_too_sick_column_slashed_even_with_answer(
    demo: SampleInputs,
) -> None:
    from tsutae.schemas import ClosedAnswer

    extra = _c2_entry(
        demo, 905, answers=[ClosedAnswer(question_key="diarrhea", value="none")]
    )
    kwargs = {**demo.build_kwargs(), "entries": [*demo.entries, extra]}
    html = _html(demo, build_report_data(**kwargs))
    cls = _cell_html(html, "c2-diarrhea", 5).split("|")[0]
    assert "st-none" in cls and "slash" in cls  # 回答があっても列の斜線は消えない
    assert "slash" in _cell_html(html, "c2-numbness", 5).split("|")[0]
    assert "slash" not in _cell_html(html, "c2-diarrhea", 6).split("|")[0]


def test_unprocessed_note_does_not_assert_masking_leak() -> None:
    # 標準最終日より後の自由記載は黙って外す（W2b の決定。未処理に数えない）。
    # 未処理は伏せ字漏れの疑いの記録だけで、紙には「伏せ字漏れ」と書かない
    from datetime import datetime

    from tsutae.config import JST
    from tsutae.pipeline.inputs import prepare_input
    from tsutae.report.sample import result_from_labels
    from tsutae.schemas import Entry

    visit = date(2026, 11, 11)
    sample = load_demo_inputs(visit_date=visit)
    late = Entry(
        id=906,
        patient_id=sample.patient_id,
        recorded_at=datetime(2026, 11, 10, 20, 0, tzinfo=JST),
        record_date=date(2026, 11, 10),
        kind="free_text",
        by_proxy=False,
        skill_version="regimen-folfox@1",
        free_text="きょうもしびれがある",
    )
    entries = [*sample.entries, late]
    prepared = prepare_input(
        courses=sample.courses,
        entries=entries,
        regimen_skill=sample.regimen_skill,
        report_skill=sample.report_skill,
        visit_date=visit,
    )
    assert {u.reason for u in prepared.unprocessed} == {"unknown_before_honorific"}
    assert late.id not in prepared.entry_ids.values()
    kwargs = {
        **sample.build_kwargs(),
        "entries": entries,
        "prepared": prepared,
        "result": result_from_labels(prepared, sample.labels),
    }
    section = _section(_html(sample, build_report_data(**kwargs)), "attention")
    assert "未処理の記載あり" in section and "1件" in section
    assert "伏せ字漏れ" not in section
    assert "院内画面" in section
