import { useCallback, useEffect, useState } from "react";

/**
 * 「つらくて書けない」の確認の種類。
 * - auto: 何も入れていない。3秒たつと「はい」を自動で押す
 * - manual: 入れた内容がある（送らずに捨てる）。「はい」を押した時だけ記録する
 */
export type ConfirmMode = "auto" | "manual";

/**
 * 確認を開く・閉じる。開いた時に入力があれば manual、無ければ auto。
 * auto の間に何か入れたら manual に変える（入れた内容を自動で捨てない）。一度 manual に
 * なったら、入力を消しても auto には戻さない。
 */
export function useTooSickConfirm(inputGiven: boolean): {
  mode: ConfirmMode | null;
  open: () => void;
  close: () => void;
} {
  const [opened, setOpened] = useState<ConfirmMode | null>(null);

  useEffect(() => {
    if (opened === "auto" && inputGiven) {
      setOpened("manual");
    }
  }, [opened, inputGiven]);

  const open = useCallback(
    () => setOpened(inputGiven ? "manual" : "auto"),
    [inputGiven],
  );
  const close = useCallback(() => setOpened(null), []);
  // effect を待たずに、入力があった描画から manual として扱う（タイマーをすぐ止める）
  const mode = opened === "auto" && inputGiven ? "manual" : opened;
  return { mode, open, close };
}
