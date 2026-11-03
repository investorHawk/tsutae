// 案 A 物語型「ある患者の 14 日間」（docs/video/storyboards.md の表を写したもの）
import type { Scene } from "../types";

export const TITLE_A = "案 A 物語型「ある患者の 14 日間」";

export const scenesA: Scene[] = [
  {
    id: "a01-title",
    seconds: 8,
    kind: "title",
    screen: "「つたえ」／化学療法の 2 週間を、診察室の A4 一枚に",
    narration:
      "つたえ。化学療法中の 2 週間の記録を、診察室の A4 一枚にするアプリです。",
    props: {
      lines: ["化学療法の 2 週間を、", "診察室の A4 一枚に"],
      tag: "外来化学療法の患者さんと医師のために",
    },
  },
  {
    id: "a02-problem",
    seconds: 14,
    kind: "problem",
    title: "診察室で起きていること",
    screen:
      "診察室の図。医師「2 週間分を 3 分で聞き取る」／患者「日付が思い出せない・言い忘れる」",
    narration:
      "外来化学療法の診察では、医師が 2 週間分の症状を 3 分ほどかけて聞き取ります。患者さんは日付を思い出せず、つらかったことほど言い忘れます。",
    props: {
      bubbles: [
        { who: "doctor", text: "2 週間分を 3 分で聞き取る" },
        { who: "patient", text: "日付が思い出せない" },
        { who: "patient", text: "つらかったことほど言い忘れる" },
      ],
    },
  },
  {
    id: "a03-today",
    seconds: 12,
    kind: "footage",
    footage: ["F1"],
    title: "毎日の記録",
    screen: "毎日、3 択と自由記載。自由記載の一文を拡大",
    narration:
      "患者さんは毎日、大きなボタンの 3 択に答え、自由に書き残します。「おとといの夜から口内炎がいたい」。この一文を覚えておいてください。",
    props: { callouts: ["「おとといの夜から口内炎がいたい」"] },
  },
  {
    id: "a04-too-sick",
    seconds: 6,
    kind: "footage",
    footage: ["F2"],
    title: "つらくて書けない",
    screen: "つらくて書けない",
    narration: "つらい日は、このボタン 1 つ。押したこと自体が記録になります。",
    props: { callouts: ["押したこと自体が記録に"] },
  },
  {
    id: "a05-fever",
    seconds: 8,
    kind: "footage",
    footage: ["F3"],
    title: "38.0℃ 以上",
    screen: "38.0℃ 以上は施設の案内文。AI は関与しない",
    narration:
      "38 度以上の体温には、施設が決めた案内文がそのまま出ます。判断しているのはコードの比較で、AI ではありません。",
    props: { callouts: ["施設の案内文をコードが出す（AI は関与しない）"] },
  },
  {
    id: "a06-visit",
    seconds: 10,
    kind: "footage",
    footage: ["F4"],
    title: "受診日",
    screen: "受診日。院内の QR → 受付番号 → 「先生に届けました」",
    narration:
      "受診日。待合で院内の QR を読み、受付番号を入れるだけ。患者さんの画面に AI の文は一度も出ません。",
    props: { callouts: ["患者さんの画面に AI の文は出ない"] },
  },
  {
    id: "a07-pipeline",
    seconds: 16,
    kind: "pipeline",
    title: "サーバーの中",
    screen: "伏せ字二段 → H1 → 主エージェント＋3 役 → H2 → A4",
    narration:
      "サーバーでは、まず人名や電話を伏せ字にし、取り残しがあれば送りません。Claude の主エージェントが 3 人の担当、日付・用語・食い違いに分け、引用が原文に無い記載は検問で突き返します。",
  },
  {
    id: "a08-visits",
    seconds: 6,
    kind: "footage",
    footage: ["F5"],
    title: "印刷待ち",
    screen: "印刷待ち → 印刷",
    narration: "医師の画面には印刷待ちが並びます。",
  },
  {
    id: "a09-printer",
    seconds: 6,
    kind: "footage",
    footage: ["F6"],
    title: "紙で届く",
    screen: "プリンタから紙",
    narration: "紙で、診察室に届きます。電子カルテとつなぐ必要はありません。",
  },
  {
    id: "a10-report",
    seconds: 20,
    kind: "report",
    title: "受診時レポート",
    screen: "要確認 → 経過表 → 症状別 → 引用（Day5 口腔粘膜炎を強調）",
    narration:
      "要確認が先頭に。Day5 の食い違い、Day8 の発熱、つらくて書けない日が前のコースと同じ Day3〜5。経過表はコースの日数で並び、あの「おとといの夜から口内炎」は Day5 の口腔粘膜炎として原文の引用つきで載っています。医師は 30 秒で、聞くべきことが決まります。",
    props: { focus: ["alerts", "timeline", "symptoms", "quotes"] },
  },
  {
    id: "a11-settings",
    seconds: 14,
    kind: "footage",
    footage: ["F8"],
    title: "一文で設定を変える",
    screen: "「口内炎は、食事がとれたかも次から聞いて」→ 差分 → 承認",
    narration:
      "医師が一文で頼むと、Claude が質問集の Skill を書き換えます。差分を見て承認したものだけが反映されます。",
    props: { callouts: ["「口内炎は、食事がとれたかも次から聞いて」"] },
  },
  {
    id: "a12-new-question",
    seconds: 6,
    kind: "footage",
    footage: ["F9"],
    title: "翌日の質問",
    screen: "翌日の患者画面に新しい質問",
    narration:
      "翌日から患者さんの画面に新しい質問。過去の日は未設問として区別されます。",
  },
  {
    id: "a13-promises",
    seconds: 14,
    kind: "promises",
    screen: "AI がしないこと 5 つ＋患者情報の扱い 3 つ",
    narration:
      "AI がしないこと。重さの判定、受診判断、患者への助言、欠けた記録の補完、食い違いの解決。氏名は集めず、受付番号は送らず、ログに文面は残しません。",
    props: {
      dont: [
        "重さの判定",
        "受診判断",
        "患者への助言",
        "欠けた記録の補完",
        "食い違いの解決",
      ],
      privacy: ["氏名は集めない", "受付番号は送らない", "ログに文面を残さない"],
    },
  },
  {
    id: "a14-closing",
    seconds: 10,
    kind: "closing",
    screen:
      "3 分 → 30 秒／日付 93%・引用 100%／テスト 3896／Built with Claude Code",
    narration:
      "聞き取り 3 分が 30 秒に。日付の一致 93%、引用の一致 100%。症例は全て合成。Built with Claude Code。",
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
