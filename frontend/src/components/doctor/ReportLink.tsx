import { reportUrl } from "../../api/doctor";

/**
 * レポート（A4 の HTML）を別のタブで開く小さなリンク。印刷ダイアログが開かない時の逃げ道
 * （『レポートを開く』から ⌘P）でもあるので、「印刷」のある所には必ず並べる。
 */
export default function ReportLink({ visitId }: { visitId: number }) {
  return (
    <a
      className="d-sublink"
      href={reportUrl(visitId)}
      target="_blank"
      rel="noopener noreferrer"
    >
      レポートを開く
    </a>
  );
}
