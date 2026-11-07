// 原稿の変更の処理（ブラウザ・サーバー・テストで共通の純粋な関数）。

/** 字幕は 1 つの文なので、前後の空白と改行を除く */
export const normalizeScript = (text) => text.replace(/[\r\n]+/g, "").trim();

/** 空白を除いた字数（台本の字数と同じ数え方） */
export const countChars = (text) => Array.from(text.replace(/\s/g, "")).length;

/** 最長共通部分列の表（a[i:] と b[j:] の長さ） */
const lcsTable = (a, b) => {
  const table = Array.from({ length: a.length + 1 }, () =>
    new Array(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] =
        a[i] === b[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  return table;
};

/** 中央の文字の並びを、1 文字ずつの操作にする（削除を追加より先に） */
const middleOps = (a, b) => {
  const table = lcsTable(a, b);
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      ops.push({ type: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (
      i < a.length &&
      (j === b.length || table[i + 1][j] >= table[i][j + 1])
    ) {
      ops.push({ type: "del", text: a[i] });
      i += 1;
    } else {
      ops.push({ type: "add", text: b[j] });
      j += 1;
    }
  }
  return ops;
};

const mergeOps = (ops) =>
  ops.reduce((merged, op) => {
    const last = merged[merged.length - 1];
    if (last && last.type === op.type) {
      return [
        ...merged.slice(0, -1),
        { type: op.type, text: last.text + op.text },
      ];
    }
    return [...merged, { ...op }];
  }, []);

/** 文字単位の差分。[{ type: "same" | "del" | "add", text }] */
export const diffChars = (before, after) => {
  const a = Array.from(before);
  const b = Array.from(after);
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
  let tail = 0;
  while (
    tail < a.length - head &&
    tail < b.length - head &&
    a[a.length - 1 - tail] === b[b.length - 1 - tail]
  ) {
    tail += 1;
  }
  const same = (chars) => chars.map((text) => ({ type: "same", text }));
  return mergeOps([
    ...same(a.slice(0, head)),
    ...middleOps(
      a.slice(head, a.length - tail),
      b.slice(head, b.length - tail),
    ),
    ...same(a.slice(a.length - tail)),
  ]);
};

/**
 * Claude Code に貼り付ける相談の文。/btw で今の作業を止めずに聞く。
 * 複数行や長い文は貼り付けで折りたたまれることがあるので、1 行に収める
 */
export const consultPrompt = ({ index, title, budget, original, edited }) =>
  [
    `/btw デモ動画のナレーション原稿の変更を確認してください。`,
    `場面 ${index}「${title}」（目標 ${budget.toFixed(1)} 秒以内）。`,
    `元の文:「${original}」`,
    `変更後:「${edited}」`,
    `字数: ${countChars(original)} → ${countChars(edited)}。`,
    `次の 3 点に短く答えてください。`,
    `(1) つたえの実際の動きと合っているか`,
    `(2) 声に出して読んで自然か`,
    `(3) 目標の時間内に読めそうか。`,
    `問題があれば修正案を 1 つ出してください。`,
  ].join(" ");
