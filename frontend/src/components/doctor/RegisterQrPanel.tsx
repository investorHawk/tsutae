import QrImage from "./QrImage";

interface RegisterQrPanelProps {
  patientId: string;
  url: string;
  onClose: () => void;
}

/** D1 の登録用QR。患者のスマホで読み取ると仮名IDがスマホに保存される。 */
export default function RegisterQrPanel({
  patientId,
  url,
  onClose,
}: RegisterQrPanelProps) {
  return (
    <section className="d-qr-panel" aria-label={`${patientId} の登録用QR`}>
      <div className="d-qr-panel-head">
        <h2>
          登録用QR <code>{patientId}</code>
        </h2>
        <button type="button" onClick={onClose}>
          閉じる
        </button>
      </div>
      <QrImage url={url} label={`${patientId} の登録用QR`} size={240} />
      <p className="d-muted">
        患者のスマホのカメラで読み取ってもらいます。パスワードはありません。
        このアプリは氏名を持たないので、仮名IDとの対応は院内の紙に控えてください。
      </p>
    </section>
  );
}
