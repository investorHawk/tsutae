import { describeError } from "./errors";

interface ErrorNoteProps {
  code: string;
  /** 「保存できませんでした」など、何が失敗したか */
  prefix?: string;
}

/** 失敗の表示。説明と API の code を両方出す。 */
export default function ErrorNote({ code, prefix }: ErrorNoteProps) {
  return (
    <p role="alert" className="d-error">
      {prefix ? `${prefix}: ` : ""}
      {describeError(code)}（<code>{code}</code>）
    </p>
  );
}
