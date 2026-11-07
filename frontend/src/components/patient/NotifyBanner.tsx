import { Link } from "react-router-dom";
import { isPushSupported } from "../../patient/pushDevice";
import { usePatientStrings } from "../../strings/PatientStrings";
import { settledPushState } from "./pushResend";
import { statusOfState } from "./pushState";
import { useAsync } from "./useAsync";

function BannerWhenOff() {
  const { t } = usePatientStrings();
  const loaded = useAsync(settledPushState, "push");
  if (loaded.status !== "ready" || statusOfState(loaded.data) !== "off") {
    return null;
  }
  return (
    <Link to="/settings" className="p-notify-banner">
      {t("notify.banner")}
    </Link>
  );
}

/**
 * 今日の記録の、お知らせがオフのあいだの案内の帯（設定へのリンク）。オンにできるときだけ出す。
 * 未対応の端末は API も呼ばない。読み込みの失敗も出さない（記録の邪魔をしない）。
 */
export default function NotifyBanner() {
  return isPushSupported() ? <BannerWhenOff /> : null;
}
