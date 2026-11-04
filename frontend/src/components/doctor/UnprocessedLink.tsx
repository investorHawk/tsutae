import { Link } from "react-router-dom";

/** 未処理の記載（D6）へのリンク。押せると分かるよう下線と矢印を付ける（D2-3）。 */
export default function UnprocessedLink({
  visitId,
  count,
}: {
  visitId: number;
  count: number;
}) {
  return (
    <Link className="d-warnlink" to={`/doctor/unprocessed/${visitId}`}>
      未処理 {count} 件を見る →
    </Link>
  );
}
