import { useCallback, useEffect, useState } from "react";
import { listSkillChanges, listSkills } from "../../api/doctor";
import type { SkillChange, SkillInfo } from "../../api/types";
import { isSkillChange, isSkillInfo } from "./guards";
import { listOf } from "./input";

export interface SkillCatalog {
  skills: SkillInfo[];
  /** 新しい順。読み込み前は null */
  history: SkillChange[] | null;
  /** Skill 一覧の読み込みの失敗（code）。読み直しに成功すれば null に戻る */
  skillsError: string | null;
  /** 変更の履歴の読み込みの失敗（code）。読み直しに成功すれば null に戻る */
  historyError: string | null;
  reloadSkills: () => Promise<void>;
  reloadHistory: () => Promise<void>;
}

function newestFirst(changes: SkillChange[]): SkillChange[] {
  return [...changes].sort((a, b) => b.id - a.id);
}

/**
 * D4 の Skill 一覧（GET skills）と変更の履歴（GET skill-changes）。開いた時に読む。
 * 失敗は一覧と履歴で別々に持つ（片方の成功で、もう片方の失敗を消さない）。
 */
export function useSkillCatalog(
  handleError: (err: unknown) => string,
): SkillCatalog {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [history, setHistory] = useState<SkillChange[] | null>(null);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const reloadSkills = useCallback(async () => {
    try {
      setSkills(listOf<SkillInfo>(await listSkills(), "skills", isSkillInfo));
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
    history,
    skillsError,
    historyError,
    reloadSkills,
    reloadHistory,
  };
}
