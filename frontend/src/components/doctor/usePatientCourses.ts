import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { listCourses, listPatients } from "../../api/doctor";
import type { Course, DoctorPatient } from "../../api/types";
import { isCourse, isDoctorPatient } from "./guards";
import { listOf } from "./input";

export interface PatientCourses {
  /** course_no 順。読み込み前（患者を切り替えた直後を含む）は null */
  courses: Course[] | null;
  loadError: string | null;
  /** 一覧から引いたレジメン。見つからなければ null */
  regimen: string | null;
  /** 取り直して並べた一覧を返す（失敗・古くなった応答は null） */
  reload: () => Promise<Course[] | null>;
}

/** どの患者の値か（別の患者の値は表示に使わない）。 */
interface Scoped<T> {
  pid: string;
  value: T;
}

interface Loaded {
  courses: Course[] | null;
  loadError: string | null;
}

const EMPTY: Loaded = { courses: null, loadError: null };

function byCourseNo(courses: Course[]): Course[] {
  return [...courses].sort((a, b) => a.course_no - b.course_no);
}

function valueFor<T>(scoped: Scoped<T>, pid: string, empty: T): T {
  return scoped.pid === pid ? scoped.value : empty;
}

/**
 * D2 の患者のコース一覧とレジメン（患者一覧から引く。取れなくても画面は使える）。
 * 値は患者ごと: pid が変われば前の患者の値はすぐに消え、前の患者の遅い応答
 * （と、同じ患者で後から始めた取り直しより前の応答）は捨てる（世代で見分ける）。
 */
export function usePatientCourses(
  pid: string,
  handleError: (err: unknown) => string,
): PatientCourses {
  const [loaded, setLoaded] = useState<Scoped<Loaded>>({ pid, value: EMPTY });
  const [regimen, setRegimen] = useState<Scoped<string | null>>({
    pid,
    value: null,
  });
  const generation = useRef(0);

  // 患者を切り替えたら、走っている取り直しを古いものにする（描画の確定と同時に）
  useLayoutEffect(
    () => () => {
      generation.current += 1;
    },
    [pid],
  );

  const reload = useCallback(async (): Promise<Course[] | null> => {
    generation.current += 1;
    const mine = generation.current;
    let next: Loaded;
    try {
      const body = await listCourses(pid);
      next = {
        courses: byCourseNo(listOf<Course>(body, "courses", isCourse)),
        loadError: null,
      };
    } catch (err) {
      if (mine !== generation.current) {
        return null;
      }
      setLoaded((prev) => ({
        pid,
        value: { ...valueFor(prev, pid, EMPTY), loadError: handleError(err) },
      }));
      return null;
    }
    if (mine !== generation.current) {
      return null;
    }
    setLoaded({ pid, value: next });
    return next.courses;
  }, [pid, handleError]);

  useEffect(() => {
    let active = true;
    listPatients()
      .then((res) => {
        const found = listOf<DoctorPatient>(
          res,
          "patients",
          isDoctorPatient,
        ).find((p) => p.id === pid);
        if (active) {
          setRegimen({ pid, value: found?.regimen ?? null });
        }
      })
      .catch(() => {
        if (active) {
          setRegimen({ pid, value: null });
        }
      });
    return () => {
      active = false;
    };
  }, [pid]);

  const current = valueFor(loaded, pid, EMPTY);
  return {
    courses: current.courses,
    loadError: current.loadError,
    regimen: valueFor(regimen, pid, null),
    reload,
  };
}
