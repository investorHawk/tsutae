// 撮影リスト（docs/video/storyboards.md の表のとおり）。React / remotion を import しない。
import type { FootageId } from "./types";

export type Device = "phone" | "pc" | "camera";

export interface FootageSpec {
  id: FootageId;
  slug: string;
  scene: string;
  device: Device;
  minSeconds: number;
  content: string;
  optional?: boolean;
  /** 録画ではなく静止画を置く素材の置き場所（無ければ video/public/footage/<id>.mp4） */
  target?: string;
}

export const DEVICE_LABEL: Record<Device, string> = {
  phone: "スマホ縦（9:16）",
  pc: "PC 横（16:9）",
  camera: "カメラ",
};

export const FOOTAGE: Record<FootageId, FootageSpec> = {
  F1: {
    id: "F1",
    slug: "patient_today",
    scene: "今日の記録",
    device: "phone",
    minSeconds: 14,
    content:
      "3 択を 5 問タップ → 体温 → 自由記載に「おとといの夜から口内炎がいたい」と打つ → 保存。家族の代理のチェックも一度見せる",
  },
  F2: {
    id: "F2",
    slug: "patient_too_sick",
    scene: "つらくて書けない",
    device: "phone",
    minSeconds: 6,
    content: "ボタンを押す → 確認 → 履歴に「つらくて書けない」が残る",
  },
  F3: {
    id: "F3",
    slug: "patient_fever",
    scene: "38.2℃ の案内",
    device: "phone",
    minSeconds: 8,
    content: "体温に 38.2 → 施設の案内文が出る",
  },
  F4: {
    id: "F4",
    slug: "patient_visit",
    scene: "受診",
    device: "phone",
    minSeconds: 15,
    content:
      "下の「受診」タブ → 受付番号 A-023 → 「先生に届ける」→ 「先生に届けました。」",
  },
  F5: {
    id: "F5",
    slug: "doctor_visits",
    scene: "印刷待ち",
    device: "pc",
    minSeconds: 6,
    content: "一覧 → 印刷ボタン → 印刷ダイアログ",
  },
  F6: {
    id: "F6",
    slug: "printer",
    scene: "実機印刷",
    device: "camera",
    minSeconds: 6,
    content: "プリンタから紙が出る → 手に取る",
  },
  F7: {
    id: "F7",
    slug: "doctor_pipeline",
    scene: "D5 変換ログ",
    device: "pc",
    minSeconds: 10,
    content: "任意（案 C の pipeline の背景に薄く敷く。無くても成立）",
    optional: true,
  },
  F8: {
    id: "F8",
    slug: "doctor_settings",
    scene: "D4 レジメン",
    device: "pc",
    minSeconds: 20,
    content:
      "「設定を変える」の「レジメン」→「＋ 新しいレジメン」→「Claude に伝える」に文を貼って送る → 待ち（早送り可）→ 左のフォームが埋まる →「確認へ進む」→ 確かめた印 →「採用して登録」",
  },
  F9: {
    id: "F9",
    slug: "patient_new_question",
    scene: "翌日",
    device: "phone",
    minSeconds: 6,
    content:
      "今日の記録に新しい質問「口の中のことで、食事がとりにくいことはありましたか」が出ている",
  },
  F10: {
    id: "F10",
    slug: "doctor_report",
    scene: "レポート画面",
    device: "pc",
    minSeconds: 10,
    content:
      "任意（report の場面は画像 sample-report.png で描くので無くてよい）",
    optional: true,
  },
  F11: {
    id: "F11",
    slug: "patient_reminder",
    scene: "毎日のお知らせ",
    device: "phone",
    minSeconds: 5,
    content:
      "iPhone のロック画面に届いた通知のスクリーンショット（タイトル「つたえ」、本文「今日の記録をお願いします。つらい日はボタンひとつで記録になります。」）。1 枚でよい。他のアプリの通知と実際の URL を写さない",
    target: "video/public/screens/F11-1.png",
  },
};

export const FOOTAGE_IDS = Object.keys(FOOTAGE) as FootageId[];

/** 撮影後に置く場所（カードに出す） */
export const footageTargetPath = (id: FootageId): string =>
  FOOTAGE[id].target ?? `video/public/footage/${id}.mp4`;
