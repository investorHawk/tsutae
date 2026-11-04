import { usePatientStrings } from "../../strings/PatientStrings";

/** 失敗の知らせ（定型文のキーで受け取る）。 */
export function ErrorMessage({
  messageKey,
  id,
}: {
  messageKey: string;
  id?: string;
}) {
  const { t } = usePatientStrings();
  return (
    <p className="p-error" role="alert" id={id}>
      {t(messageKey)}
    </p>
  );
}

/** 完了の知らせ（記録しました・先生に届けました 等）。 */
export function DoneMessage({ messageKey }: { messageKey: string }) {
  const { t } = usePatientStrings();
  return (
    <p className="p-done" role="status">
      {t(messageKey)}
    </p>
  );
}

/**
 * 固定規則の案内（spec 11節）。API の notices（patient_strings のキー）の文を
 * そのまま目立つ枠に出す。アプリは一文字も足さない。
 */
export function Notices({ keys }: { keys: readonly string[] }) {
  const { t } = usePatientStrings();
  const texts = keys
    .map((key) => ({ key, text: t(key) }))
    .filter((item) => item.text.length > 0);
  return (
    <>
      {texts.map((item, i) => (
        <div key={`${i}-${item.key}`} className="p-notice" role="alert">
          {item.text}
        </div>
      ))}
    </>
  );
}
