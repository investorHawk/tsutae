/**
 * 今の画面を読み直す。番号で登録した後、保存した仮名ID と Cookie で描き直すのに使う。
 * テストで差し替えられるように小さく包む（jsdom の location.reload は動かない）。
 */
export function reloadPage(): void {
  window.location.reload();
}
