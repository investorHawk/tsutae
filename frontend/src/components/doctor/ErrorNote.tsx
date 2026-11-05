import { describeError } from "./errors";

interface ErrorNoteProps {
  code: string;
  /** 「保存できませんでした」など、何が失敗したか */
  prefix?: string;
  /** code → 説明（既定は共通の表。D4 レジメンの画面は describeRegimenError） */
  describe?: (code: string) => string;
}

/** 失敗の表示。説明と API の code を両方出す。 */
export default function ErrorNote({
  code,
  prefix,
  describe = describeError,
}: ErrorNoteProps) {
  return (
    <p role="alert" className="d-error">
      {prefix ? `${prefix}: ` : ""}
      {describe(code)}（<code>{code}</code>）
    </p>
  );
}
