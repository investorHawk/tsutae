/**
 * D4 の Skill の呼び名（純関数）。画面には内部名（regimen-folfox など）ではなく
 * 医師向けの呼び名を出し、内部名は小さく添えるだけにする（D5-1）。
 */
import type { SkillInfo } from "../../api/types";

/** 名前の決まった Skill（レジメンは識別名から作るので表に持たない。T95 で2つ固定を外した）。 */
const KNOWN: Readonly<Record<string, string>> = {
  "report-format-default": "レポートの形式",
};

const REGIMEN = /^regimen-([a-z0-9][a-z0-9-]*)$/;
const REPORT_FORMAT = /^report-format-([a-z0-9][a-z0-9-]*)$/;

/** 内部名 → 呼び名。書式に合わない名前はそのまま返す。 */
export function skillDisplayName(name: string): string {
  const known = KNOWN[name];
  if (known) {
    return known;
  }
  const regimen = REGIMEN.exec(name);
  if (regimen) {
    return `${regimen[1].toUpperCase()} の質問集`;
  }
  const report = REPORT_FORMAT.exec(name);
  return report ? `レポートの形式（${report[1]}）` : name;
}

/** 旧 D4（一文の書き換え）で選べる Skill か（report-format-* だけ。spec 9.2）。 */
export function isReportFormatSkill(name: string): boolean {
  return REPORT_FORMAT.test(name);
}

/** version → 「第N版」。 */
export function versionLabel(version: number): string {
  return `第${version}版`;
}

/** 選択肢の文字列（呼び名と版）。 */
export function skillOptionLabel(skill: SkillInfo): string {
  return `${skillDisplayName(skill.name)}（${versionLabel(skill.version)}）`;
}
