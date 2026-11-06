// 案 C 信頼・仕組み型「AI に任せること、任せないこと」（docs/video/storyboards.md の表を写したもの）
import type { Scene } from "../types";

export const TITLE_C = "案 C 信頼・仕組み型「AI に任せること、任せないこと」";

export const scenesC: Scene[] = [
  {
    id: "c01-title",
    seconds: 10,
    kind: "title",
    screen:
      "「つたえ」／医療アドバイス AI ではありません。では AI は何をする？",
    narration:
      "つたえは、医療アドバイス AI ではありません。では、AI に何を任せるのか。",
    props: {
      lines: ["医療アドバイス AI ではありません。", "では AI は何をする？"],
      tag: "外来化学療法の患者さんと医師のために",
    },
  },
  {
    id: "c02-problem",
    seconds: 10,
    kind: "problem",
    title: "診察室で起きていること",
    screen: "2 週間 → 3 分、言い忘れ",
    narration:
      "外来化学療法の診察で、医師は 2 週間分の症状を 3 分かけて聞き取ります。患者さんは日付を思い出せず、言い忘れます。",
    props: {
      bubbles: [
        { who: "doctor", text: "2 週間分を 3 分で" },
        { who: "patient", text: "日付が思い出せない・言い忘れる" },
      ],
    },
  },
  {
    id: "c03-patient",
    seconds: 18,
    kind: "footage",
    footage: ["F1", "F2", "F3"],
    title: "患者さんの毎日",
    screen:
      "3 択・自由記載 → つらくて書けない → 38.2℃ の案内。「患者の画面に AI の文は出ない」",
    narration:
      "患者さんは毎日、3 択と自由記載。つらい日はボタン 1 つ。38 度以上の案内は施設の文をコードが出すだけで、患者さんの画面に AI の文は一度も出ません。",
    props: {
      split: [6, 5, 7],
      callouts: [null, null, "患者さんの画面に AI の文は出ない"],
    },
  },
  {
    id: "c04-masking",
    seconds: 14,
    kind: "masking",
    footage: ["F4"],
    title: "送る前に伏せ字",
    screen:
      "受診タブ → 受付番号。伏せ字のアニメ（「○○さん」「[病院]」）。受付番号は送らない",
    narration:
      "受診日、受診タブで受付。Claude に送る前に人名・電話・病院名を伏せ字にし、取り残しの疑いがある記録は送りません。受付番号も送りません。",
    // F4 の最低秒は 10。場面 14 秒のうち最初の 10 秒だけ録画を出し、残りは伏せ字のアニメだけ
    props: { split: [10] },
  },
  {
    id: "c05-pipeline",
    seconds: 26,
    kind: "pipeline",
    title: "Claude Agent SDK の上の変換",
    screen: "Agent SDK。主エージェント＋3 役。Hook H1〜H4 を 1 つずつ点灯",
    narration:
      "Claude Agent SDK の上に組んだ変換です。主エージェントが Skill を読み、日付・用語・食い違いの 3 役に分けます。Hook が 4 つ。送る直前に伏せ字漏れを検査する H1、引用が原文に無ければ拒否する H2、Skill の書き換え先を限る H3、許可外の道具を止める H4。",
    props: { hooks: ["H1", "H2", "H3", "H4"], backgroundFootage: "F7" },
  },
  {
    id: "c06-hookdemo",
    seconds: 10,
    kind: "hookdemo",
    title: "H2 の検問",
    screen: "要約した引用 → H2 が拒否 → 原文どおりに直して再送",
    narration:
      "たとえば「口内炎がつらい」と要約した引用は、原文に無いので拒否。Claude は原文どおり「おとといの夜から口内炎がいたい」に直して出し直します。",
  },
  {
    id: "c07-report",
    seconds: 16,
    kind: "report",
    title: "受診時レポート",
    screen: "要確認 → 経過表 → 症状別 → 引用",
    narration:
      "出来上がる A4 一枚。要確認、コース日数の経過表、症状別の時系列、そして原文の引用。医師は 30 秒で聞くべきことが決まります。",
    props: { focus: ["alerts", "timeline", "symptoms", "quotes"] },
  },
  {
    id: "c08-settings",
    seconds: 18,
    kind: "footage",
    footage: ["F8", "F9"],
    title: "設定も Skill そのもの",
    screen: "一文 → SKILL.md の差分 → 承認 → 翌日の質問",
    narration:
      "設定も Claude Code の Skill そのもの。医師が一文で頼むと Claude が SKILL.md を書き換え、差分を承認したものだけが反映。翌日から質問が変わります。",
    props: {
      split: [12, 6],
      callouts: ["差分を承認したものだけが反映", "翌日から新しい質問"],
    },
  },
  {
    id: "c09-promises",
    seconds: 16,
    kind: "promises",
    screen: "任せないこと 5 つ＋削除・ログに文面なし",
    narration:
      "任せないこと。重さの判定、受診判断、助言、欠けた記録の補完、食い違いの解決。氏名は集めず、ログに文面を残さず、印刷済みで消します。",
    props: {
      dont: [
        "重さの判定",
        "受診判断",
        "患者への助言",
        "欠けた記録の補完",
        "食い違いの解決",
      ],
      privacy: ["氏名は集めない", "ログに文面を残さない", "印刷済みで消す"],
    },
  },
  {
    id: "c10-closing",
    seconds: 12,
    kind: "closing",
    screen:
      "日付 93%・引用 100%・H2 拒否 0／59 コミット・3896 テスト／Built with Claude Code",
    narration:
      "日付の一致 93%、引用の一致 100%、H2 の拒否 0 回。開発も Claude Code で、59 コミット・3896 テスト。症例は全て合成。",
    props: {
      stats: [
        { label: "日付の一致", format: "number", to: 93, unit: "%" },
        { label: "引用の一致", format: "number", to: 100, unit: "%" },
        { label: "H2 の拒否", format: "number", to: 0, unit: "回" },
        { label: "コミット", format: "number", to: 59, unit: "" },
        { label: "テスト", format: "number", to: 3896, unit: "件" },
      ],
    },
  },
];
