/** D4 レジメンのチャットの決まった文（院内の画面だけ。Claude の文ではない）。 */

/** 往復の失敗の理由（会話の失敗の行の reason）→ 説明。 */
const TURN_FAILURES: Readonly<Record<string, string>> = {
  timeout: "時間内に返答が来ませんでした",
  max_turns: "Claude のやり取りの回数の上限に達しました",
  max_budget: "1回の往復の費用の上限に達しました",
  sdk_error: "Claude を呼び出せませんでした",
  internal_error: "サーバーで想定外の失敗がありました",
  invalid_result: "Claude の結果が検査に通りませんでした",
  code_taken: "その識別名はもう使われています",
  cancelled: "往復が取り消されました",
};

export function turnFailureText(reason: string): string {
  const why = TURN_FAILURES[reason] ?? "往復が失敗しました";
  return `${why}。フォームは変わっていません。もう一度送ってください`;
}

/** 送る文が H1 に掛かったとき（入力の文は返さず、この決まった文で知らせる）。 */
export const H1_BLOCKED_TEXT =
  "個人を特定しうる表現の疑いがあるため、送りませんでした（保存もしていません）。患者の名前・ID・番号などを消してから、もう一度送ってください。";

/** 送る文が H1 に掛かった場所（field_id）の説明。 */
export function blockedWhere(fieldId: string): string {
  return fieldId === "text"
    ? "先生の文"
    : "依頼文の他の部分（フォームの値など）";
}
