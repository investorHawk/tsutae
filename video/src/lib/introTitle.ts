// intro の題（"25 年間、消化器外科医として癌治療"）を画面の部品に分ける。React / remotion を import しない。

export interface IntroTitle {
  /** 大きく出す頭の数字（無ければ空） */
  number: string;
  /** 数字の後ろの語（"年間"）。頭が数字でなければ読点の前の全体 */
  unit: string;
  /** 最初の読点の後ろ（無ければ空） */
  sub: string;
}

export const splitIntroTitle = (title: string): IntroTitle => {
  const at = title.indexOf("、");
  const head = (at >= 0 ? title.slice(0, at) : title).trim();
  const sub = at >= 0 ? title.slice(at + 1).trim() : "";
  const m = /^(\d+)\s*(.*)$/.exec(head);
  if (!m) return { number: "", unit: head, sub };
  return { number: m[1], unit: m[2], sub };
};
