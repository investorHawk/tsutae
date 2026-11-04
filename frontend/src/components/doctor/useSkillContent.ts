import { useEffect, useState } from "react";
import { getSkill } from "../../api/doctor";
import type { SkillContentResponse } from "../../api/types";

export interface SkillContentState {
  /** 選んだ Skill のその版の中身。読み込み中・失敗なら null */
  content: SkillContentResponse | null;
  /** 読み込みの失敗（code）。無ければ null */
  error: string | null;
}

interface Loaded extends SkillContentState {
  key: string;
}

/**
 * D4: 選んだ Skill の今の中身（GET skills/{name}）。名前か版（承認で上がる）が変われば
 * 取り直す。前の Skill・前の版の中身は、新しいものが届くまで出さない（取り違えない）。
 * version が null（一覧にまだ無い）なら取らない。
 */
export function useSkillContent(
  name: string,
  version: number | null,
  handleError: (err: unknown) => string,
): SkillContentState {
  const key = version === null || name === "" ? "" : `${name}@${version}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    if (key === "") {
      return undefined;
    }
    let active = true;
    getSkill(name).then(
      (content) => {
        if (active) {
          setLoaded({ key, content, error: null });
        }
      },
      (err: unknown) => {
        if (active) {
          setLoaded({ key, content: null, error: handleError(err) });
        }
      },
    );
    return () => {
      active = false;
    };
    // name は key に含まれる
  }, [key, handleError]);

  if (loaded === null || loaded.key !== key) {
    return { content: null, error: null };
  }
  return { content: loaded.content, error: loaded.error };
}
