"""モジュール間の共通データ型（契約）。全モジュールはここから import する。

変更はオーケストレーター（メインセッション）だけが行う。実装エージェントは編集しない。
用語は docs/spec.md 2節、全体像は docs/architecture.md。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# 基本の列挙
# ---------------------------------------------------------------------------

Regimen = Literal["FOLFOX", "CAPOX"]
ThreeLevel = Literal["none", "present", "hard"]
FeverValue = Literal["not_measured", "measured"]
AnswerValue = Literal["none", "present", "hard", "not_measured", "measured"]
AnswerType = Literal["three_level", "temperature"]
EntryKind = Literal["too_sick", "answers", "free_text", "mixed"]
SymptomStatus = Literal["present", "improving", "absent"]
VisitStatus = Literal["generating", "ready", "printed", "failed"]
SkillChangeStatus = Literal["pending", "approved", "rejected", "failed"]

QUESTION_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,40}$"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Skill（.claude/skills/<name>/SKILL.md の frontmatter）
# ---------------------------------------------------------------------------


class Question(Frozen):
    key: str = Field(pattern=QUESTION_KEY_PATTERN)
    text: str = Field(min_length=1, max_length=200)
    answer_type: AnswerType


class FixedRule(Frozen):
    """緊急時の固定規則。判定はコードの閾値比較。文面は patient_strings.json のキー。"""

    key: str = Field(pattern=QUESTION_KEY_PATTERN)
    question_key: str = Field(pattern=QUESTION_KEY_PATTERN)
    threshold_celsius: float = Field(ge=35.0, le=42.0, allow_inf_nan=False)
    patient_string_key: str


class RegimenSkill(Frozen):
    name: str
    description: str
    version: int = Field(ge=1)
    regimen: Regimen
    cycle_days: int = Field(ge=7, le=42)
    pump_removal_day: int | None = Field(default=None, ge=1)
    questions: list[Question] = Field(min_length=1)
    fixed_rules: list[FixedRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _keys_unique_and_rules_valid(self) -> RegimenSkill:
        keys = [q.key for q in self.questions]
        if len(keys) != len(set(keys)):
            raise ValueError("questions の key が重複している")
        by_key = {q.key: q for q in self.questions}
        for rule in self.fixed_rules:
            if rule.question_key not in by_key:
                raise ValueError(f"fixed_rule {rule.key} が未知の質問を参照している")
            if by_key[rule.question_key].answer_type != "temperature":
                raise ValueError(f"fixed_rule {rule.key} は体温の質問だけを参照できる")
        if (
            self.pump_removal_day is not None
            and self.pump_removal_day > self.cycle_days
        ):
            raise ValueError("pump_removal_day が cycle_days を超えている")
        return self

    @property
    def skill_version(self) -> str:
        return f"{self.name}@{self.version}"


class ReportFormatSkill(Frozen):
    name: str
    description: str
    version: int = Field(ge=1)
    sections: list[Literal["header", "attention", "grid", "per_symptom", "quotes"]] = (
        Field(min_length=1)
    )
    show_previous_course: bool = True
    show_temperature_row: bool = True
    quotes_max_items: int = Field(default=30, ge=0, le=200)
    low_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # 要確認に「発熱」として並べる体温（コードの比較。トリアージではない）
    fever_attention_celsius: float = Field(default=37.5, ge=35.0, le=42.0)

    @property
    def skill_version(self) -> str:
        return f"{self.name}@{self.version}"


# ---------------------------------------------------------------------------
# 患者の記録
# ---------------------------------------------------------------------------


class ClosedAnswer(Frozen):
    question_key: str = Field(pattern=QUESTION_KEY_PATTERN)
    value: AnswerValue
    temperature: float | None = Field(default=None, ge=30.0, le=45.0)

    @model_validator(mode="after")
    def _temperature_rule(self) -> ClosedAnswer:
        if self.value == "measured" and self.temperature is None:
            raise ValueError("measured のときは temperature が必須")
        if self.value != "measured" and self.temperature is not None:
            raise ValueError("temperature は measured のときだけ")
        return self


class EntryCreate(Frozen):
    """患者 API が受け取る1回分の記録。"""

    too_sick: bool = False
    by_proxy: bool = False
    answers: list[ClosedAnswer] = Field(default_factory=list)
    free_text: str | None = Field(default=None, max_length=2000)

    @field_validator("free_text")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def _not_empty(self) -> EntryCreate:
        if self.too_sick and (self.answers or self.free_text):
            raise ValueError("too_sick のときは回答・自由記載を付けない")
        if not self.too_sick and not self.answers and not self.free_text:
            raise ValueError("空の記録は保存しない")
        keys = [a.question_key for a in self.answers]
        if len(keys) != len(set(keys)):
            raise ValueError("同じ質問への回答が重複している")
        return self

    @property
    def kind(self) -> EntryKind:
        if self.too_sick:
            return "too_sick"
        if self.answers and self.free_text:
            return "mixed"
        return "answers" if self.answers else "free_text"


class Entry(Frozen):
    """保存済みの記録（DB から読んだもの）。"""

    id: int
    patient_id: str
    recorded_at: datetime  # tz-aware JST
    record_date: date  # recorded_at の JST 日付
    kind: EntryKind
    by_proxy: bool
    skill_version: str
    answers: list[ClosedAnswer] = Field(default_factory=list)
    free_text: str | None = None


class Course(Frozen):
    id: int | None = None
    patient_id: str
    course_no: int = Field(ge=1)
    infusion_date: date  # 実投与日 = Day1
    planned_date: date | None = None  # 予定日（延期の注記に使う）
    next_visit: date | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# パイプライン入力（Claude に送るもの。仮名ID・受付番号は含めない）
# ---------------------------------------------------------------------------


class MaskedEntry(Frozen):
    entry_no: int = Field(ge=1)  # 今回の変換内での通し番号
    record_date: date
    day: int | None  # 今コースの Day（コース外なら None）
    by_proxy: bool
    too_sick: bool
    answers: list[ClosedAnswer] = Field(default_factory=list)
    masked_free_text: str | None = None  # 一次置換済み


class CourseSchedule(Frozen):
    course_no: int
    infusion_date: date
    day1_date: date
    last_day_date: date  # 次の投与前日（不明なら cycle_days から）
    pump_removal_date: date | None
    previous_infusion_date: date | None
    delay_days: int | None  # 予定より何日延期したか


class PipelineInput(Frozen):
    regimen: Regimen
    regimen_skill_version: str
    report_skill_version: str
    schedule: CourseSchedule
    questions: list[Question]
    entries: list[MaskedEntry]


# ---------------------------------------------------------------------------
# パイプライン出力（emit_timeline / emit_report の入力スキーマ）
# ---------------------------------------------------------------------------


class TimelineEvent(Frozen):
    entry_no: int = Field(ge=1)
    date: date  # 出来事の暦日（回想なら記録日より前）
    day: int | None
    course_no: int
    term: str = Field(min_length=1)  # CTCAE v5.0 JCOG版の用語名（Grade は出さない）
    question_key: str | None = None  # 対応するクローズ質問（経過表の ○ に使う）
    status: SymptomStatus
    source_quote: str = Field(min_length=1)  # 伏せ字後の原文に部分一致すること（H2）
    confidence: float = Field(ge=0.0, le=1.0)
    recalled: bool = False
    by_proxy: bool = False


class Contradiction(Frozen):
    entry_no: int = Field(ge=1)
    date: date
    day: int | None
    question_key: str
    closed_answer: AnswerValue
    free_text_quote: str = Field(min_length=1)


class UnprocessedEntry(Frozen):
    entry_id: int
    reason: str  # 検出規則名のみ（原文は入れない）


class Timeline(Frozen):
    events: list[TimelineEvent] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    unprocessed_entries: list[UnprocessedEntry] = Field(default_factory=list)


class SymptomSummary(Frozen):
    term: str
    question_key: str | None = None
    start_day: int | None
    start_date: date
    representative_quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ReportPicks(Frozen):
    """emit_report の入力。AI が決めるのは症状別時系列の選び方だけ。"""

    per_symptom: list[SymptomSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# レポート描画の入力（決定的に組み立てる。AI は HTML を書かない）
# ---------------------------------------------------------------------------

CellState = Literal["none", "present", "hard", "no_input", "not_asked", "too_sick"]


class GridCell(Frozen):
    day: int
    state: CellState
    free_text_mark: bool = False  # 自由記載にその症状の記述あり（○）
    recalled_mark: bool = False  # ○ が回想由来（回）
    temperature: float | None = None


class GridRow(Frozen):
    course_no: int
    question_key: str  # 体温行は "temperature"
    label: str
    is_previous_course: bool
    cells: list[GridCell]


class GridColumn(Frozen):
    day: int
    date: date | None
    by_proxy: bool = False  # 列頭に「代」
    too_sick: bool = False  # 列全体を斜線


class Grid(Frozen):
    days: list[int]
    columns: list[GridColumn]
    rows: list[GridRow]


class AttentionItem(Frozen):
    kind: Literal["contradiction", "fever", "too_sick", "unprocessed"]
    day: int | None = None
    question_key: str | None = None
    closed_answer: str | None = None
    quote: str | None = None
    temperature: float | None = None
    previous_course_same_day: bool = False
    count: int | None = None


class ReportHeader(Frozen):
    reception_no: str
    patient_id: str
    regimen: Regimen
    course_no: int
    course_start: date
    course_end: date
    recorded_days: int
    total_days: int
    no_input_days: int
    too_sick_days: int
    delay_note: str | None = None
    fallback: bool = False


class QuoteItem(Frozen):
    entry_no: int
    day: int | None
    date: date
    text: str  # 伏せ字後の原文そのまま
    by_proxy: bool = False


class ReportData(Frozen):
    header: ReportHeader
    attention: list[AttentionItem]
    grid: Grid
    per_symptom: list[SymptomSummary]
    quotes: list[QuoteItem]
    fallback: bool = False
    report_skill_version: str


# ---------------------------------------------------------------------------
# 合成データと正解ラベル（data/synthetic/*.json）
# ---------------------------------------------------------------------------

HardCaseTag = Literal["contradiction", "mild_improving", "relative_time", "negation"]


class SyntheticCourse(Frozen):
    course_no: int
    infusion_date: date
    planned_date: date | None = None
    next_visit: date | None = None
    note: str | None = None


class SyntheticEntry(Frozen):
    seq: int = Field(ge=1)  # ファイル内の通し番号（ラベルが参照する）
    recorded_at: datetime
    too_sick: bool = False
    by_proxy: bool = False
    skill_version: str = "regimen-folfox@1"
    answers: list[ClosedAnswer] = Field(default_factory=list)
    free_text: str | None = None


class SyntheticPatient(Frozen):
    patient_id: str
    role: Literal["demo", "eval"]
    regimen: Regimen
    visit_date: date  # この日に受診（QR）する想定
    reception_no: str
    courses: list[SyntheticCourse]
    entries: list[SyntheticEntry]


class LabelEvent(Frozen):
    date: date
    day: int | None
    course_no: int
    term: str
    question_key: str | None = None
    status: SymptomStatus
    source_quote: str
    recalled: bool = False


class LabelContradiction(Frozen):
    question_key: str
    closed_answer: AnswerValue
    free_text_quote: str


class EntryLabel(Frozen):
    entry_seq: int
    events: list[LabelEvent] = Field(default_factory=list)
    contradictions: list[LabelContradiction] = Field(default_factory=list)
    hard_case_tags: list[HardCaseTag] = Field(default_factory=list)
    expect_unprocessed: bool = False  # 二次検出で送信対象外になるべき記録
    note: str | None = None


class PatientLabels(Frozen):
    patient_id: str
    labels: list[EntryLabel]


# ---------------------------------------------------------------------------
# パイプラインの受け渡し（W2）
# ---------------------------------------------------------------------------


class PreparedInput(Frozen):
    """伏せ字・選別を済ませた変換の入力。レポート組み立てとフォールバックも使う。"""

    input: PipelineInput
    entry_ids: dict[int, int]  # entry_no -> entries.id
    masked_texts: dict[int, str]  # entry_no -> 一次置換後の自由記載
    unprocessed: list[UnprocessedEntry] = Field(default_factory=list)


class RunStats(Frozen):
    duration_ms: int = 0
    num_turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


class ConversionResult(Frozen):
    """変換の結果。timeline が None ならフォールバック（AI変換なし）。"""

    timeline: Timeline | None
    picks: ReportPicks | None
    fallback: bool
    error_code: str | None = (
        None  # 例: "timeout", "max_turns", "sdk_error", "no_timeline", "h1_blocked"
    )
    stats: RunStats = Field(default_factory=RunStats)
