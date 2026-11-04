/**
 * 医師 API の応答の検査。正本は api/doctorGuards.ts（API 関数の中で使う）。
 * 画面側の既存の import のために同じものを出し直す。
 */
export {
  OPEN_VISIT_STATUSES,
  VISIT_STATUSES,
  isCourse,
  isCreatePatientResponse,
  isCreateSkillChangeResponse,
  isDoctorPatient,
  isInvalidSkill,
  isOpenVisitStatus,
  isPipelineEvent,
  isSkillChange,
  isSkillInfo,
  isUnprocessedItem,
  isVisitHeader,
  isVisitStatus,
  isVisitSummary,
} from "../../api/doctorGuards";
