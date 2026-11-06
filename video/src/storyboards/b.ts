// 案 B ビフォーアフター型「3 分が 30 秒になる」（推奨。docs/video/storyboards.md の表を写したもの）
import type { Scene } from "../types";

export const TITLE_B = "案 B ビフォーアフター型「3 分が 30 秒になる」";

export const scenesB: Scene[] = [
  {
    id: "b01-coldopen",
    seconds: 8,
    kind: "coldopen",
    screen: "大きな「3:00」が「0:30」に変わる → 「つたえ」",
    narration: "診察室の 3 分を、30 秒に。つたえ。",
    props: { lines: ["化学療法の 2 週間を、診察室の A4 一枚に"] },
  },
  {
    id: "b02-before",
    seconds: 18,
    kind: "before",
    title: "いまの診察室",
    screen:
      "吹き出しの会話。時計が 3:00 まで回る。損失 3 つ: 日付が曖昧・言い忘れ・食い違いに気づかない",
    narration:
      "外来化学療法の診察。「下痢はいつからでしたか」「えっと、先週の…」「口内炎は」「あ、言い忘れてました」。医師は 2 週間分を 3 分かけて聞き取り、それでも日付は曖昧で、言い忘れが残り、答えの食い違いには気づけません。",
    props: {
      bubbles: [
        { who: "doctor", text: "下痢はいつからでしたか" },
        { who: "patient", text: "えっと、先週の…" },
        { who: "doctor", text: "口内炎は" },
        { who: "patient", text: "あ、言い忘れてました" },
      ],
      losses: ["日付が曖昧", "言い忘れ", "食い違いに気づかない"],
    },
  },
  {
    id: "b03-after",
    seconds: 16,
    kind: "after",
    title: "つたえがある診察室",
    screen: "机に A4。要確認 3 行が光る。時計 0:30",
    narration:
      "つたえがあると、診察の前に A4 一枚が机にあります。先頭に要確認。Day5 の食い違い、Day8 の発熱、つらくて書けなかった 3 日間。医師は 30 秒で、何を聞くべきかが決まります。",
    props: {
      alerts: [
        "Day5 の食い違い",
        "Day8 の発熱 37.9℃",
        "つらくて書けなかった 3 日間",
      ],
    },
  },
  {
    id: "b04-patient",
    seconds: 14,
    kind: "footage",
    footage: ["F1", "F2"],
    title: "患者さんの毎日",
    screen:
      "3 択・自由記載「おとといの夜から口内炎がいたい」→ つらくて書けない → 家族の代理",
    narration:
      "患者さんは毎日、3 択と自由記載。つらい日はボタン 1 つで、押したこと自体が記録に。家族が代わりに入力することもできます。日々思っていたことが、言い忘れなく医師に届きます。",
    props: {
      split: [8, 6],
      callouts: [
        "「おとといの夜から口内炎がいたい」",
        "言い忘れなく医師に届く",
      ],
    },
  },
  {
    id: "b05-visit",
    seconds: 8,
    kind: "footage",
    footage: ["F4"],
    title: "受診日",
    screen: "受診タブ → 受付番号 → 先生に届けました",
    narration:
      "受診日は受診タブで受付番号を入れて送るだけ。患者さんの画面に AI の文は出ません。",
    props: { callouts: ["患者さんの画面に AI の文は出ない"] },
  },
  {
    id: "b06-pipeline",
    seconds: 16,
    kind: "pipeline",
    title: "サーバーの中",
    screen: "伏せ字 → 主＋3 役 → H2 → A4。「食い違いは解決せず並べる」",
    narration:
      "伏せ字にしてから Claude へ。主エージェントが日付・用語・食い違いの 3 人の担当に分け、原文に無い引用は検問で突き返します。食い違いは解決せず、並べて示します。",
    props: { notes: ["食い違いは解決せず、並べて示す"] },
  },
  {
    id: "b07-report",
    seconds: 18,
    kind: "report",
    title: "受診時レポート",
    screen:
      "経過表（前コースと同じ Day、−−、代、回）→ 症状別の時系列（Day5 口内炎と原文の引用）",
    narration:
      "経過表はコースの日数で並び、前のコースと同じ Day で比べられます。入力なし、つらくて書けない、症状なし、未設問を区別。「おとといの夜から口内炎」は Day5 の口内炎として、原文の引用つきで載ります。",
    props: { focus: ["timeline", "symptoms"] },
  },
  {
    id: "b08-settings",
    seconds: 18,
    kind: "footage",
    footage: ["F8", "F9"],
    title: "一文で質問を変える",
    screen: "一文 → 差分 → 承認 → 翌日の新しい質問",
    narration:
      "医師が「口内炎は、食事がとれたかも次から聞いて」と一文で頼むと、Claude が質問集の Skill を書き換え、差分を承認したものだけが反映。翌日から患者さんの質問が変わります。",
    props: {
      split: [12, 6],
      callouts: [
        "「口内炎は、食事がとれたかも次から聞いて」",
        "翌日から新しい質問",
      ],
    },
  },
  {
    id: "b09-promises",
    seconds: 14,
    kind: "promises",
    screen: "AI がしないこと 5 つ＋情報の扱い 3 つ",
    narration:
      "AI がしないこと。重さの判定、受診判断、助言、補完、食い違いの解決。氏名は集めず、受付番号は送らず、印刷済みで消します。",
    props: {
      dont: [
        "重さの判定",
        "受診判断",
        "患者への助言",
        "欠けた記録の補完",
        "食い違いの解決",
      ],
      privacy: ["氏名は集めない", "受付番号は送らない", "印刷済みで消す"],
    },
  },
  {
    id: "b10-closing",
    seconds: 20,
    kind: "closing",
    screen: "3:00 → 0:30 再掲 → 数字 → Built with Claude Code",
    narration:
      "3 分が、30 秒に。日付の一致 93%、引用の一致 100%、テスト 3896 件。症例は全て合成。Built with Claude Code。",
    props: {
      stats: [
        { label: "聞き取り", format: "clock", from: 180, to: 30 },
        { label: "日付の一致", format: "number", to: 93, unit: "%" },
        { label: "引用の一致", format: "number", to: 100, unit: "%" },
        { label: "テスト", format: "number", to: 3896, unit: "件" },
      ],
    },
  },
];
