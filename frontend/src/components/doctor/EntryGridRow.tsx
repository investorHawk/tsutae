import type { DoctorEntry, DoctorEntryAnswer } from "../../api/types";
import { valueLabel } from "./answerLabels";
import { formatClock, formatDay } from "./dayLabel";
import type { GridColumn, VisitDay } from "./entryGrid";

const NONE = "—";

/** 「なし」は薄い灰の「—」（読み上げは「なし」）。 */
function NoneMark({ label = "なし" }: { label?: string }) {
  return (
    <>
      <span aria-hidden="true">{NONE}</span>
      <span className="visually-hidden">{label}</span>
    </>
  );
}

function LevelCell({ answer }: { answer: DoctorEntryAnswer | undefined }) {
  if (!answer) {
    return <td className="d-grid-cell" />;
  }
  if (answer.value === "none") {
    return (
      <td className="d-grid-cell d-grid-cell--none">
        <NoneMark />
      </td>
    );
  }
  const tone = answer.value === "hard" ? "hard" : "present";
  return (
    <td className={`d-grid-cell d-grid-cell--${tone}`}>
      {valueLabel(answer.value)}
    </td>
  );
}

function TemperatureCell({
  answer,
}: {
  answer: DoctorEntryAnswer | undefined;
}) {
  if (!answer) {
    return <td className="d-grid-cell" />;
  }
  if (answer.value === "measured" && answer.temperature !== null) {
    return <td className="d-grid-cell">{answer.temperature.toFixed(1)}℃</td>;
  }
  return (
    <td className="d-grid-cell d-grid-cell--none">
      {valueLabel(answer.value)}
    </td>
  );
}

function AnswerCells({
  entry,
  columns,
}: {
  entry: DoctorEntry;
  columns: readonly GridColumn[];
}) {
  if (entry.kind === "too_sick") {
    // 症状の列（と体温）をまたいで1つのセルにする。紺の地は「つらい」と同じ意味
    return (
      <td
        className="d-grid-cell d-grid-cell--hard"
        colSpan={Math.max(columns.length, 1)}
      >
        つらくて書けない
      </td>
    );
  }
  if (columns.length === 0) {
    return <td className="d-grid-cell" />;
  }
  return (
    <>
      {columns.map((column) => {
        const answer = entry.answers.find((a) => a.question_key === column.key);
        return column.kind === "temperature" ? (
          <TemperatureCell key={column.key} answer={answer} />
        ) : (
          <LevelCell key={column.key} answer={answer} />
        );
      })}
    </>
  );
}

function DayCell({ entry }: { entry: DoctorEntry }) {
  if (entry.day === null) {
    return (
      <td className="d-grid-cell d-grid-cell--none">
        <NoneMark label="コース外" />
      </td>
    );
  }
  return (
    <td className="d-grid-cell" title={`第${entry.course_no}コース`}>
      Day{entry.day}
    </td>
  );
}

/** 記録1件の行: 記録日（＋時刻）・Day・症状ごと・体温・自由記載（有無）・代理。 */
export function EntryGridRow({
  entry,
  columns,
}: {
  entry: DoctorEntry;
  columns: readonly GridColumn[];
}) {
  return (
    <tr>
      <th scope="row">
        {formatDay(entry.record_date)}
        <span className="d-grid-time">{formatClock(entry.recorded_at)}</span>
      </th>
      <DayCell entry={entry} />
      <AnswerCells entry={entry} columns={columns} />
      <td
        className={`d-grid-cell${entry.has_free_text ? "" : " d-grid-empty"}`}
      >
        {entry.has_free_text ? "あり" : <NoneMark label="なし" />}
      </td>
      {entry.by_proxy ? (
        <td className="d-grid-cell d-grid-cell--proxy" title="代理入力">
          代
        </td>
      ) : (
        <td className="d-grid-cell d-grid-empty">
          <NoneMark label="本人" />
        </td>
      )}
    </tr>
  );
}

/** 受診日の行（受付の時刻の位置。緑の線の中央に「受診日 11月9日（月）」）。 */
export function VisitDayRow({
  visit,
  colSpan,
}: {
  visit: VisitDay;
  colSpan: number;
}) {
  return (
    <tr className="d-grid-visit">
      <td colSpan={colSpan}>
        <span className="d-grid-visit-line">
          受診日 {formatDay(visit.visit_date)}
        </span>
      </td>
    </tr>
  );
}
