/**
 * API の失敗の扱い（医師画面）。サーバーは {"error": "<code>"} を返す。
 * 画面には日本語の説明と code をそのまま並べる（code は API が増やしてもよい）。
 */
import { isApiError, UNKNOWN_ERROR } from "../../api/http";

const MESSAGES: Readonly<Record<string, string>> = {
  network_error: "サーバーにつながりません",
  unknown_error: "処理できませんでした",
  invalid_response: "サーバーの応答を読めませんでした",
  not_found: "見つかりません",
  not_logged_in: "ログインしてください",
  unauthorized: "ログインしてください",
  unknown_patient: "その仮名IDの患者は登録されていません",
  course_duplicate: "同じコース番号がすでにあります",
  course_order: "実投与日がコース番号の順に増えていません",
  course_patient_mismatch: "別の患者のコースが混ざっています",
  course_not_found: "そのコースは登録されていません",
  schedule_mismatch: "日程とコースが合いません",
  invalid_course_no: "コース番号は1以上の整数で入れてください",
  missing_infusion_date: "実投与日を入れてください",
  invalid_date: "日付は YYYY-MM-DD の形で、暦にある日を入れてください",
  note_too_long: "メモは200字までです",
  invalid_visit_id: "受診の番号が正しくありません",
  generating:
    "変換の最中です。終わってから印刷・印刷済みにしてください（数分かかることがあります）",
  not_regenerable:
    "この受診は今はもう一度変換できません（生成中・AI の結果あり（伏せ字の保存なし）・印刷済み・期限切れ）",
  bad_password: "パスワードが違います",
  // 未処理の記載（D6）の伏せ字
  visit_closed:
    "印刷済み・期限切れの受診です（伏せ字は保存できません。レポートも消えています）",
  invalid_spans: "伏せる範囲が原文と合いません。選び直してください",
  unknown_entry: "その記録はこの受診の未処理の記載ではありません",
  not_confirmable:
    "仮名ID・受付番号が残っている記録は、確かめても送れません。伏せ字にしてください",
  // Skill の書き換え（D4。409 は pending のまま、やり直せるものを含む）
  busy: "ほかの書き換え・承認・却下を処理中です。少し待ってからもう一度押してください",
  use_regimen_editor:
    "レジメンは一文の書き換えでは直せません。D4 のレジメンの画面（フォームとチャット）で直してください",
  stale_request:
    "書き換えが途中で中断されました（サーバーの再起動など）。もう一度依頼してください",
  timeout: "書き換えが時間内に終わりませんでした",
  not_pending: "この変更はもう承認待ちではありません（履歴を見てください）",
  stale:
    "依頼の後に Skill が変わったため承認できません。もう一度依頼してください",
  version_conflict: "Skill の version が合わないため承認できません",
  write_error: "Skill を書き込めませんでした",
  lock_error: "Skill のロックを取れませんでした",
  editor_unavailable: "書き換えの仕組みが使えません",
  invalid_name: "Skill の名前が正しくありません",
  invalid_request: "依頼の一文が空か、長すぎます",
  unknown_skill: "その Skill はありません",
  base_invalid: "今の SKILL.md が壊れているため書き換えられません",
  no_change: "書き換えても中身が変わりませんでした",
  h1_blocked: "依頼の一文に個人を特定しうる語があるため送りませんでした",
  invalid_input: "入力の形が正しくありません",
  internal_error: "サーバーで想定外の失敗がありました",
  // D4 レジメン（下書き・Claude の1往復・確認・採用。v1.1）
  working:
    "Claude の応答中です。返答が来てから、もう一度操作してください（左の欄は編集できません）",
  not_open:
    "この下書きはもう閉じています（採用か破棄の後です）。読み直してください",
  conflict:
    "読んでから保存するまでに、ほかの変更（Claude の返答など）が先に入りました。読み直したので、もう一度入れてください",
  invalid_fields: "入れた値を保存できませんでした。欄の下の理由を見てください",
  invalid_form:
    "採用の前の検査に掛かりました。下の理由を見て、フォームを直してください",
  token_mismatch:
    "確認の画面を出した後に値が変わりました。確認の画面を出し直したので、もう一度確かめてください",
  ai_values_unconfirmed:
    "AI が入れた値を確かめていません。「上の値を全て確かめました」に印を付けてください",
  schedule_locked:
    "このレジメンには患者がいるため、1コースの日数・薬の Day・ポンプ抜去日は変えられません。変えるときは新しいレジメンとして作ってください",
  code_taken:
    "その識別名はもう使われています（ほかのレジメンか、開いている別の下書き）。別の識別名にしてください",
  draft_exists:
    "このレジメンには開いている下書きがあります。読み直してください",
  form_unavailable:
    "このレジメンの版にはフォームがありません（旧 D4 で作った版）。新しいレジメンとして作ってください",
  render_failed: "フォームから SKILL.md を描けませんでした",
  key_taken: "その key はもう使われています（部品集の外した問も含む）",
  unknown_row: "その行はもうありません。読み直してください",
  code_locked: "既存のレジメンの識別名は変えられません",
};

/**
 * D4 レジメンの画面だけで意味の変わる code（旧 D4 の Skill の書き換えと同じ code）。
 * 画面は `describeRegimenError` で引く（無ければ共通の表）。
 */
const REGIMEN_MESSAGES: Readonly<Record<string, string>> = {
  stale:
    "下書きを作った後にこのレジメンの版が変わりました。この下書きを捨てて、開き直してください",
  version_conflict:
    "このレジメンの版が合わないため採用できません。この下書きを捨てて、開き直してください",
  timeout:
    "Claude の返答が時間内に来ませんでした。フォームは変わっていません。もう一度送ってください",
  h1_blocked:
    "個人を特定しうる表現の疑いがあるため、送りませんでした（保存もしていません）",
  busy: "ほかの採用・保存を処理中です。少し待ってからもう一度押してください",
};

export function errorCode(err: unknown): string {
  return isApiError(err) ? err.code : UNKNOWN_ERROR;
}

export function isUnauthorized(err: unknown): boolean {
  return isApiError(err) && err.isUnauthorized;
}

export function describeError(code: string): string {
  return MESSAGES[code] ?? MESSAGES[UNKNOWN_ERROR];
}

/** D4 レジメンの画面の説明（同じ code でも旧 D4 と意味の違うものを先に引く）。 */
export function describeRegimenError(code: string): string {
  return REGIMEN_MESSAGES[code] ?? describeError(code);
}
