import { useSearchParams } from "react-router-dom";
import { isValidPid } from "../../patient/pid";
import { usePatientStrings } from "../../strings/PatientStrings";

const STEP_KEYS = [
  "guide.step_share",
  "guide.step_add",
  "guide.step_open",
  "guide.step_number",
] as const;

/**
 * iPhone のブラウザで出す「ホーム画面に追加」の案内（docs/plan-device-records.md §5.8）。
 * 登録も記録もさせない。URL の番号はアプリで入れ直すので大きく見せる（形が正しいときだけ）。
 * LINE などのアプリ内ブラウザには追加の項目が無いので、Safari で開き直す案内を手順の前に出す
 * （UA では見分けきれないので、いつも出す）。
 */
export default function AddToHomeGuide() {
  const { t } = usePatientStrings();
  const [params] = useSearchParams();
  const pid = (params.get("pid") ?? "").trim();
  return (
    <section className="page">
      <h1>{t("guide.title")}</h1>
      <p>{t("guide.about")}</p>
      <p>{t("guide.in_app_browser")}</p>
      <ol className="p-guide-steps">
        {STEP_KEYS.map((key) => (
          <li key={key}>{t(key)}</li>
        ))}
      </ol>
      {isValidPid(pid) && (
        <div className="p-guide-number">
          <p className="p-guide-number-label">{t("register.number_label")}</p>
          <p className="p-guide-number-value">{pid}</p>
        </div>
      )}
    </section>
  );
}
