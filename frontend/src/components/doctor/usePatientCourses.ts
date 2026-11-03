import { useCallback, useEffect, useState } from "react";
import { listCourses, listPatients } from "../../api/doctor";
import type { Course, DoctorPatient } from "../../api/types";
import { isCourse, isDoctorPatient } from "./guards";
import { listOf } from "./input";

export interface PatientCourses {
  /** course_no 順。読み込み前は null */
  courses: Course[] | null;
  loadError: string | null;
  /** 一覧から引いたレジメン。見つからなければ null */
  regimen: string | null;
  /** 取り直して並べた一覧を返す（失敗は null） */
  reload: () => Promise<Course[] | null>;
}

function byCourseNo(courses: Course[]): Course[] {
  return [...courses].sort((a, b) => a.course_no - b.course_no);
}

/** D2 の患者のコース一覧とレジメン（患者一覧から引く。取れなくても画面は使える）。 */
export function usePatientCourses(
  pid: string,
  handleError: (err: unknown) => string,
): PatientCourses {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [regimen, setRegimen] = useState<string | null>(null);

  const reload = useCallback(async (): Promise<Course[] | null> => {
    try {
      const list = byCourseNo(
        listOf<Course>(await listCourses(pid), "courses", isCourse),
      );
      setCourses(list);
      setLoadError(null);
      return list;
    } catch (err) {
      setLoadError(handleError(err));
      return null;
    }
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
          setRegimen(found?.regimen ?? null);
        }
      })
      .catch(() => {
        if (active) {
          setRegimen(null);
        }
      });
    return () => {
      active = false;
    };
  }, [pid]);

  return { courses, loadError, regimen, reload };
}
