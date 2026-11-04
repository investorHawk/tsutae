import type { MaskCheckResponse } from "../../api/types";
import MarkedText from "./MarkedText";
import { mergeSpans } from "./maskSpans";

interface MaskCheckResultProps {
  check: MaskCheckResponse;
  confirmed: boolean;
  onConfirm: (confirmed: boolean) => void;
}

/**
 * 「伏せ字を確かめる」の結果（サーバーが再検出したもの）。送られる文（伏せた後）と、
 * まだ疑われる語の強調。疑いが残り、確かめて送れる記録には「個人を特定する語は無いことを
 * 確かめた」のチェックを出す（確かめなければ未処理のまま残る）。
 */
export default function MaskCheckResult({
  check,
  confirmed,
  onConfirm,
}: MaskCheckResultProps) {
  return (
    <div className="d-mask-check">
      <p className="d-mask-label">送られる文（Claude に届く形）</p>
      <p className="d-sent">
        <MarkedText
          text={check.masked_text}
          marks={mergeSpans(check.suspects)}
        />
      </p>
      {check.sendable ? (
        <p className="d-ok">疑わしい語はありません。この文で送ります。</p>
      ) : null}
      {!check.sendable && check.confirmable ? (
        <>
          <p className="d-mask-warn">
            まだ疑わしい語があります（強調した所）。個人を特定する語でなければ、確かめてから送れます。確かめなければ未処理のまま残ります。
          </p>
          <label className="d-mask-confirm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => onConfirm(e.target.checked)}
            />
            個人を特定する語は無いことを確かめた
          </label>
        </>
      ) : null}
      {!check.sendable && !check.confirmable ? (
        <p className="d-mask-warn">
          仮名ID・受付番号など、確かめても送れない語が残っています。伏せ字にしないと送れません（未処理のまま残ります）。
        </p>
      ) : null}
    </div>
  );
}
