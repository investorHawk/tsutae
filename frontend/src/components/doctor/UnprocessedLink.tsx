import { Link } from "react-router-dom";
import "./board.css";

/** 印刷待ちの表の上に1回だけ出す補足（「要確認」のある受診があるとき）。 */
export const UNPROCESSED_HINT =
  "「要確認」は伏せ字漏れの疑いで紙に載らない記載です。印刷の前に開いて確かめてください";

/** 「要確認」の印の説明（紙に載らないので、印刷の前に見る）。 */
export const UNPROCESSED_TITLE =
  "伏せ字漏れの疑いで Claude に送らなかった記載です。紙には載らないので、印刷の前に開いて確かめてください";

/**
 * 未処理の記載（D6）へのリンク。橙の「要確認 N件」の印にする（紙に載らない記載なので、
 * 印刷の前に見てほしい）。0件の時は呼び出し側で何も出さない。
 */
export default function UnprocessedLink({
  visitId,
  count,
}: {
  visitId: number;
  count: number;
}) {
  return (
    <Link
      className="d-warnlink"
      to={`/doctor/unprocessed/${visitId}`}
      title={UNPROCESSED_TITLE}
    >
      要確認 {count}件
    </Link>
  );
}
