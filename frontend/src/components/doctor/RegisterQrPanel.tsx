import QrImage from "./QrImage";

interface RegisterQrPanelProps {
  patientId: string;
  url: string;
  onClose: () => void;
}

/**
 * D1 の登録用QR。患者のスマホで読み取ると仮名IDがスマホに保存される。
 * ホーム画面のアプリは QR の登録を引き継げないので、同じ仮名IDを「登録の番号」として
 * 隣に大きく出し、患者に手で入れてもらう。
 */
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
      <div className="d-qr-body">
        <QrImage url={url} label={`${patientId} の登録用QR`} size={240} />
        <dl className="d-qr-number">
          <dt>登録の番号</dt>
          <dd className="d-qr-number-value">{patientId}</dd>
        </dl>
      </div>
      <p className="d-muted">
        患者のスマホのカメラで読み取ってもらいます。ホーム画面のアプリでは、この番号を入れてもらいます。パスワードはありません。
        このアプリは氏名を持たないので、仮名IDとの対応は院内の紙に控えてください。
      </p>
    </section>
  );
}
