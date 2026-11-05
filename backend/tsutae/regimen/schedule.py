"""投与スケジュールから描く文と「日付の言い方の表」（architecture 9c）。

- 点滴の日の集合 I（route=infusion の全 Day。pump は入れない）・ポンプ抜去日 P
  （pump の最後の Day）・内服の範囲 O
- |I|=1 なら FOLFOX/CAPOX と同じ行。|I|≥2 なら「記録日以前で最も近い点滴の日」と
  候補を並べ、confidence を下げる（D2 で登録するのは Day1 だけ。spec 9.1）
- 直し方が「DayN」だけの行は、同じ Day なら1行にまとめる（Day1 と飲み薬を始めた日）
- 入力は validate_complete_form を通ったフォーム（必須の欄が埋まっている）
"""

from __future__ import annotations

from dataclasses import dataclass

from tsutae.regimen.form import DayRange, DrugRow, RegimenForm

LOW_CONFIDENCE_NOTE = "confidence を下げる（0.6 未満）"
STANDARD_NOTE = "標準の場合。施設の指示が違えば confidence を下げる"


@dataclass(frozen=True)
class Schedule:
    cycle_days: int
    infusion_days: tuple[int, ...]
    pump: DrugRow | None
    oral: DrugRow | None

    @property
    def pump_removal_day(self) -> int | None:
        return self.pump.days[-1].end if self.pump is not None else None

    @property
    def oral_ranges(self) -> tuple[DayRange, ...]:
        return tuple(self.oral.days) if self.oral is not None else ()

    @property
    def rest_starts(self) -> tuple[int, ...]:
        """内服の範囲の後ろの休薬の始まり（1コースの終わりまで続く範囲の後は無い）。"""
        return tuple(r.end + 1 for r in self.oral_ranges if r.end < self.cycle_days)


@dataclass(frozen=True)
class DateRow:
    phrases: tuple[str, ...]
    target: str  # 直し方の欄
    merge_day: int | None = None  # 直し方が「DayN」だけのときの N（同じ N はまとめる）

    @property
    def left(self) -> str:
        return "・".join(self.phrases)


def build_schedule(form: RegimenForm) -> Schedule:
    cycle_days = form.basic.cycle_days
    if cycle_days is None:
        raise ValueError("cycle_days が無い")
    days: set[int] = set()
    for drug in form.drugs:
        if drug.route == "infusion":
            for r in drug.days:
                days.update(range(r.start, r.end + 1))
    return Schedule(
        cycle_days=cycle_days,
        infusion_days=tuple(sorted(days)),
        pump=next((d for d in form.drugs if d.route == "pump"), None),
        oral=next((d for d in form.drugs if d.route == "oral"), None),
    )


# ---------------------------------------------------------------------------
# Day の書き方
# ---------------------------------------------------------------------------


def compact_days(days: tuple[int, ...] | list[int]) -> str:
    """Day1・8・15"""
    return "Day" + "・".join(str(d) for d in days)


def compact_ranges(ranges: list[DayRange] | tuple[DayRange, ...]) -> str:
    """Day1・8・15／Day1〜3／Day1〜5・8〜12"""
    parts = [
        str(r.start) if r.start == r.end else f"{r.start}〜{r.end}" for r in ranges
    ]
    return "Day" + "・".join(parts)


def explicit_ranges(ranges: list[DayRange] | tuple[DayRange, ...]) -> str:
    """Day1〜Day14／Day1〜Day5・Day8〜Day12"""
    return "・".join(
        f"Day{r.start}" if r.start == r.end else f"Day{r.start}〜Day{r.end}"
        for r in ranges
    )


def rest_ranges(schedule: Schedule) -> tuple[DayRange, ...]:
    """内服の範囲の間と最後の範囲の後（1コースの終わりまで）。"""
    ranges = schedule.oral_ranges
    ends = [*(r.start - 1 for r in ranges[1:]), schedule.cycle_days]
    return tuple(
        DayRange(start=r.end + 1, end=end)
        for r, end in zip(ranges, ends, strict=True)
        if r.end + 1 <= end
    )


def _candidates(days: tuple[int, ...], nearest: str, note: str) -> str:
    """1つなら「DayN（標準…）」、複数なら「記録日以前で最も近い<nearest>（DayA・B）。<note>」。"""
    if len(days) == 1:
        return f"Day{days[0]}（{STANDARD_NOTE}）"
    return f"記録日以前で最も近い{nearest}（{compact_days(days)}）。{note}"


# ---------------------------------------------------------------------------
# 日付の言い方の表
# ---------------------------------------------------------------------------


def _infusion_rows(schedule: Schedule) -> list[DateRow]:
    days = schedule.infusion_days
    if len(days) <= 1:
        return [
            DateRow(("点滴の日", "投与日", "病院で点滴した日"), "Day1（実投与日）", 1),
            DateRow(("点滴の次の日", "点滴の翌日"), "Day2", 2),
        ]
    later = compact_days(days[1:])
    following = tuple(d + 1 for d in days if d + 1 <= schedule.cycle_days)
    return [
        DateRow(
            ("点滴の日", "投与日", "病院で点滴した日"),
            f"記録日以前で最も近い点滴の日（{compact_days(days)}）。"
            f"{later} は延期を記録していないので {LOW_CONFIDENCE_NOTE}",
        ),
        DateRow(
            ("点滴の次の日", "点滴の翌日"),
            f"上の点滴の日の次の日（{compact_days(following)}）。{LOW_CONFIDENCE_NOTE}",
        ),
    ]


def _pump_rows(schedule: Schedule) -> list[DateRow]:
    removal = schedule.pump_removal_day
    if removal is None:
        return []
    rows = [
        DateRow(
            ("ポンプを外した日", "ポンプを抜いた日"), f"Day{removal}（ポンプ抜去日）"
        )
    ]
    if removal + 1 <= schedule.cycle_days:
        rows.append(
            DateRow(("ポンプを外した次の日",), f"Day{removal + 1}", removal + 1)
        )
    return rows


def _oral_rows(schedule: Schedule) -> list[DateRow]:
    ranges = schedule.oral_ranges
    if not ranges:
        return []
    first = ranges[0].start
    rows = [DateRow(("飲み薬を始めた日",), f"Day{first}", first)]
    if len(ranges) == 1:  # CAPOX と同じ文言
        rows.append(
            DateRow(
                ("飲み薬が終わった日", "最後に飲んだ日"),
                f"Day{ranges[0].end}（{STANDARD_NOTE}）",
            )
        )
        if schedule.rest_starts:
            rows.append(
                DateRow(
                    ("休薬に入った日", "飲み薬が休みになった日"),
                    f"Day{schedule.rest_starts[0]}（同上）",
                )
            )
        return rows
    note = f"どれか決まらなければ {LOW_CONFIDENCE_NOTE}"
    rows.append(
        DateRow(
            ("飲み薬が終わった日", "最後に飲んだ日"),
            _candidates(tuple(r.end for r in ranges), "内服の最後の日", note),
        )
    )
    if schedule.rest_starts:
        rows.append(
            DateRow(
                ("飲み薬が休みの日", "休薬に入った日"),
                _candidates(
                    schedule.rest_starts,
                    "休薬の始まりの日",
                    f"休みの何日目か書かれていなければ {LOW_CONFIDENCE_NOTE}",
                ),
            )
        )
    rows.append(
        DateRow(
            ("飲み薬を再開した日", "また飲み始めた日"),
            _candidates(tuple(r.start for r in ranges[1:]), "内服の再開の日", note),
        )
    )
    return rows


def _no_pump_rows(schedule: Schedule, display_name: str) -> list[DateRow]:
    if schedule.pump is not None:
        return []
    return [
        DateRow(
            ("「ポンプ」が出てくる表現",),
            f"{display_name} にポンプは無い。日付を決めず記録日を `date` にし、"
            "confidence を下げる",
        )
    ]


def _merge(rows: list[DateRow]) -> list[DateRow]:
    """直し方が同じ Day だけの行を、先に出た行にまとめる（言い方を後ろに足す）。"""
    merged: list[DateRow] = []
    for row in rows:
        same = next(
            (
                i
                for i, m in enumerate(merged)
                if row.merge_day is not None and m.merge_day == row.merge_day
            ),
            None,
        )
        if same is None:
            merged.append(row)
        else:
            base = merged[same]
            merged[same] = DateRow(
                base.phrases + row.phrases, base.target, base.merge_day
            )
    return merged


def date_rows(schedule: Schedule, display_name: str) -> list[DateRow]:
    """表の「投与スケジュールから決まる行」（曜日の3行・今日の3行は共通でテンプレート）。"""
    return _merge(
        [
            *_infusion_rows(schedule),
            *_pump_rows(schedule),
            *_oral_rows(schedule),
            *_no_pump_rows(schedule, display_name),
        ]
    )


# ---------------------------------------------------------------------------
# §1 投与スケジュールの箇条
# ---------------------------------------------------------------------------


def _infusion_line(form: RegimenForm, schedule: Schedule) -> list[str]:
    days = schedule.infusion_days
    if len(days) <= 1:
        return []
    per_drug = "、".join(
        f"{d.name} {compact_ranges(d.days)}"
        for d in form.drugs
        if d.route == "infusion"
    )
    return [
        f"点滴は {compact_days(days)}（{per_drug}）。登録されるのは Day1 の日付だけで、"
        f"{compact_days(days[1:])} の点滴が予定どおりだったかは分からない"
    ]


def _oral_line(schedule: Schedule, oral_note: str) -> list[str]:
    oral = schedule.oral
    if oral is None:
        return []
    ranges = schedule.oral_ranges
    total = sum(r.end - r.start + 1 for r in ranges)
    rests = rest_ranges(schedule)
    rest = f"、{explicit_ranges(rests)} が休薬" if rests else ""
    return [
        f"{oral.start_note}飲み薬（{oral.name}）を1日{oral.times_per_day}回、"
        f"{total}日間飲む。標準は {explicit_ranges(ranges)} が内服{rest}{oral_note}"
    ]


def schedule_lines(
    form: RegimenForm,
    schedule: Schedule,
    *,
    cycle_note: str,
    day1_note: str,
    pump_sentence: str,
    no_pump_note: str,
    oral_note: str,
) -> list[str]:
    """§1 の箇条（「延期があっても」より前）。"""
    n = schedule.cycle_days
    lines = [f"1コースは{n}日{cycle_note}。**Day1 = 実投与日**（{day1_note}）"]
    lines += _infusion_line(form, schedule)
    removal = schedule.pump_removal_day
    if removal is not None:
        lines += [
            pump_sentence,
            f"**Day{removal} にポンプを外す**（ポンプ抜去日。入力の "
            "`schedule.pump_removal_date`）",
        ]
    lines += _oral_line(schedule, oral_note)
    if removal is None:
        lines.append(
            f"**持続ポンプは無い**（{no_pump_note}ポンプ抜去日は無い。"
            "`schedule.pump_removal_date` は null）"
        )
    lines.append(
        f"今コースは次コースの実投与日の前日まで。Day{n} までが標準だが、"
        f"それを過ぎた記録も今コースの Day{n + 1}, Day{n + 2}… として数える"
    )
    return lines


def schedule_keys(schedule: Schedule) -> str:
    keys = ["day1_date"]
    if schedule.pump is not None:
        keys.append("pump_removal_date")
    keys += ["last_day_date", "previous_infusion_date"]
    return "・".join(f"`{k}`" for k in keys)
