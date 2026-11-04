import { useCallback, useEffect, useState } from "react";
import { listSkillChanges, listSkills } from "../../api/doctor";
import type { InvalidSkill, SkillChange, SkillInfo } from "../../api/types";
import { isInvalidSkill, isSkillChange, isSkillInfo } from "./guards";
import { listOf } from "./input";

export interface SkillCatalog {
  skills: SkillInfo[];
  /** 読めない Skill（壊れた SKILL.md・欠けた必須 Skill）。必須を先に、名前順 */
  invalid: InvalidSkill[];
  /** 新しい順。読み込み前は null */
  history: SkillChange[] | null;
  /** Skill 一覧の読み込みの失敗（code）。読み直しに成功すれば null に戻る */
  skillsError: string | null;
  /** 変更の履歴の読み込みの失敗（code）。読み直しに成功すれば null に戻る */
  historyError: string | null;
  reloadSkills: () => Promise<void>;
  reloadHistory: () => Promise<void>;
}

function requiredFirst(items: InvalidSkill[]): InvalidSkill[] {
  return [...items].sort(
    (a, b) =>
      Number(b.required) - Number(a.required) || a.name.localeCompare(b.name),
  );
}

function newestFirst(changes: SkillChange[]): SkillChange[] {
  return [...changes].sort((a, b) => b.id - a.id);
}

/**
 * D4 の Skill 一覧（GET skills の skills と invalid）と変更の履歴（GET skill-changes）。開いた時に読む。
 * 失敗は一覧と履歴で別々に持つ（片方の成功で、もう片方の失敗を消さない）。
 */
export function useSkillCatalog(
  handleError: (err: unknown) => string,
): SkillCatalog {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [invalid, setInvalid] = useState<InvalidSkill[]>([]);
  const [history, setHistory] = useState<SkillChange[] | null>(null);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const reloadSkills = useCallback(async () => {
    try {
      const body = await listSkills();
      setSkills(listOf<SkillInfo>(body, "skills", isSkillInfo));
      setInvalid(
        requiredFirst(listOf<InvalidSkill>(body, "invalid", isInvalidSkill)),
      );
      setSkillsError(null);
    } catch (err) {
      setSkillsError(handleError(err));
    }
  }, [handleError]);

  const reloadHistory = useCallback(async () => {
    try {
      const body = await listSkillChanges();
      setHistory(
        newestFirst(listOf<SkillChange>(body, "skill_changes", isSkillChange)),
      );
      setHistoryError(null);
    } catch (err) {
      setHistoryError(handleError(err));
    }
  }, [handleError]);

  useEffect(() => {
    void reloadSkills();
    void reloadHistory();
  }, [reloadSkills, reloadHistory]);

  return {
    skills,
    invalid,
    history,
    skillsError,
    historyError,
    reloadSkills,
    reloadHistory,
  };
}
