import QRCode, { type QRCodeToStringOptions } from "qrcode";
import { useEffect, useState } from "react";

/** SVG で描く（canvas の無い環境でも同じ経路で描ける）。 */
export const QR_OPTIONS: QRCodeToStringOptions = {
  type: "svg",
  errorCorrectionLevel: "M",
  margin: 2,
  color: { dark: "#000000", light: "#ffffff" },
};

export function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

interface QrImageProps {
  url: string;
  /** img の alt（例「P-AB12CD34 の登録用QR」） */
  label: string;
  size?: number;
}

type QrState = { url: string; src: string | null; failed: boolean };

/** 登録用QR（register_url）を qrcode で SVG の data URL にして描く。 */
export default function QrImage({ url, label, size = 220 }: QrImageProps) {
  const [qr, setQr] = useState<QrState>({ url, src: null, failed: false });

  useEffect(() => {
    let active = true;
    QRCode.toString(url, QR_OPTIONS)
      .then((svg) => {
        if (active) {
          setQr({ url, src: svgDataUrl(svg), failed: false });
        }
      })
      .catch(() => {
        if (active) {
          setQr({ url, src: null, failed: true });
        }
      });
    return () => {
      active = false;
    };
  }, [url]);

  const current = qr.url === url;
  return (
    <figure className="d-qr">
      {current && qr.src ? (
        <img src={qr.src} alt={label} width={size} height={size} />
      ) : null}
      {current && qr.failed ? (
        <p className="d-error">QR を描けませんでした</p>
      ) : null}
      <figcaption className="d-qr-url">{url}</figcaption>
    </figure>
  );
}
