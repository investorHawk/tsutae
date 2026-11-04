import type { PatientPreviewQuestion } from "../../../api/regimenTypes";

interface PhonePreviewProps {
  regimenName: string;
  questions: readonly PatientPreviewQuestion[];
}

/**
 * 採用した後の患者のスマホの見本（医師画面の部品。患者の画面のファイルは使わない）。
 * 出すのは採用される質問の文と回答の型だけ（Claude の文は出さない）。選択肢の文字は
 * 患者の画面の定型文（answer.none など）と同じ言葉にしてある。
 */
export default function PhonePreview({
  regimenName,
  questions,
}: PhonePreviewProps) {
  return (
    <section className="rf-phone-wrap" aria-labelledby="rf-phone-h">
      <h3 id="rf-phone-h">採用すると、患者のスマホはこうなります</h3>
      <p className="d-muted rf-hint">
        変わるのは次の記録から。それまでの記録は今の版のまま表示・集計します。
      </p>
      <div className="rf-phone" role="group" aria-label="患者のスマホの見本">
        <p className="rf-phone-title">今日の記録（{regimenName}）</p>
        <p className="rf-phone-sub">あてはまるものを押してください</p>
        <ol className="rf-phone-qs">
          {questions.map((q, i) => (
            <li key={q.key ?? i} className="rf-phone-q">
              <span>{q.text ?? "（文が未入力）"}</span>
              {q.answer_type === "temperature" ? (
                <span className="rf-pills">
                  <span className="rf-pill">測った（℃）</span>
                  <span className="rf-pill">測っていない</span>
                </span>
              ) : (
                <span className="rf-pills">
                  <span className="rf-pill">なし</span>
                  <span className="rf-pill">ある</span>
                  <span className="rf-pill">つらい</span>
                </span>
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
