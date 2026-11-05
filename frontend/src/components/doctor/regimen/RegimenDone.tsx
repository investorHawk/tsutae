import type { AdoptRegimenResponse } from "../../../api/regimenTypes";

export interface AdoptedRegimen {
  result: AdoptRegimenResponse;
  displayName: string;
  isNew: boolean;
  questionCount: number;
  cycleDays: number | null;
}

interface RegimenDoneProps {
  adopted: AdoptedRegimen;
  onBack: () => void;
}

/** 登録済み（採用の後）。患者の画面が変わるのは次の記録から。 */
export default function RegimenDone({ adopted, onBack }: RegimenDoneProps) {
  const { result, displayName, isNew } = adopted;
  const items = isNew
    ? [
        `患者を登録するとき、レジメンに「${displayName}」を選べます`,
        `${displayName} の患者には、次の記録から ${adopted.questionCount} 問を聞きます`,
        `受診時のレポートは ${result.skill_name} 版 ${result.version} を読み、1コース ${adopted.cycleDays ?? "—"} 日で Day を数えます`,
        // 部品集に入るのは、まだ無かった3択の質問だけ（無ければ何も足さない）
        "部品集に無かった質問があれば、それも部品集に入れました（次のレジメンから選べます）",
      ]
    : [
        `${displayName} の患者には、次の記録から新しい質問集で聞きます`,
        `それまでの記録は版 ${result.version - 1} の質問集のまま表示・集計します`,
        "版の履歴に全文を残しました",
      ];
  return (
    <section className="rf-section rf-done" aria-labelledby="rf-done-h">
      <h3 id="rf-done-h" tabIndex={-1}>
        {isNew
          ? `${result.skill_name} 版 ${result.version} を登録しました`
          : `${displayName} を版 ${result.version} にしました`}
      </h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <div>
        <button type="button" onClick={onBack}>
          一覧に戻る
        </button>
      </div>
    </section>
  );
}
