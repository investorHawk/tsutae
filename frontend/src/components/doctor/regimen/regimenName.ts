/** D4 レジメンの名前の出し方（タブ・見出し・確認で同じ文言と判定を使う）。 */

/** レジメン名が空のときの文言（「＋ 新しいレジメン」のタブとは別の、下書きの名前）。 */
export const UNNAMED_REGIMEN = "新しいレジメン";

/** 入っている名前。null・空文字・空白だけなら null。 */
export function filledName(name: string | null | undefined): string | null {
  return name && name.trim() !== "" ? name : null;
}

/** 画面に出す名前（空なら「新しいレジメン」）。 */
export function regimenNameOf(name: string | null | undefined): string {
  return filledName(name) ?? UNNAMED_REGIMEN;
}
