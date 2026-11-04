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
  /**
   * 患者一覧から引いたこの患者の行（要約の行: 今のコースと Day・最後の記録日・次回受診。
   * API が今日で計算する）。読み込み前・見つからなければ null
   */
  patient: DoctorPatient | null;
  /** コースを取り直して並べた一覧を返す（失敗・古くなった応答は null） */
  reload: () => Promise<Course[] | null>;
  /** 患者の行を取り直す（コースを保存した後。今のコース・Day・次回受診が変わる） */
  reloadPatient: () => void;
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
 * D2 の患者のコース一覧と、患者一覧のこの患者の行（レジメン・要約。取れなくても画面は使える）。
 * 値は患者ごと: pid が変われば前の患者の値はすぐに消え、前の患者の遅い応答
 * （と、同じ患者で後から始めた取り直しより前の応答）は捨てる（世代で見分ける）。
 */
export function usePatientCourses(
  pid: string,
  handleError: (err: unknown) => string,
): PatientCourses {
  const [loaded, setLoaded] = useState<Scoped<Loaded>>({ pid, value: EMPTY });
  const [patient, setPatient] = useState<Scoped<DoctorPatient | null>>({
    pid,
    value: null,
  });
  const [patientRound, setPatientRound] = useState(0);
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

  // 取り直し（patientRound）では、前の行を消さずに置き換える（要約の行がちらつかない）。
  // 失敗したら前の行を残す（取り直しの失敗で要約を消さない）
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
          setPatient({ pid, value: found ?? null });
        }
      })
      .catch(() => {
        if (active) {
          setPatient((prev) => ({ pid, value: valueFor(prev, pid, null) }));
        }
      });
    return () => {
      active = false;
    };
  }, [pid, patientRound]);

  const reloadPatient = useCallback(() => setPatientRound((n) => n + 1), []);
  const current = valueFor(loaded, pid, EMPTY);
  const found = valueFor(patient, pid, null);
  return {
    courses: current.courses,
    loadError: current.loadError,
    regimen: found?.regimen ?? null,
    patient: found,
    reload,
    reloadPatient,
  };
}
