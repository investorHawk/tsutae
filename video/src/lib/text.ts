// 字数の数え方（テストと文書の生成で共用）: 空白（半角・全角・改行）を除いた文字数。
export const countChars = (text: string): number =>
  Array.from(text.replace(/[\s　]/g, "")).length;
