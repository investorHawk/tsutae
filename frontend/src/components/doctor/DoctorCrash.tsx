/** 医師画面の描画で例外が出たときの知らせ（ErrorBoundary の fallback）。 */
export default function DoctorCrash() {
  return (
    <p className="d-error" role="alert">
      画面を表示できませんでした。再読み込みするか、別の画面に移ってください。
    </p>
  );
}
