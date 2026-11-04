import "@testing-library/jest-dom/vitest";
import { dayLabelClock } from "../components/doctor/dayLabel";

// 医師画面の日付の「今年」（年を付けるか）をテストの日に止める（fixture の日時と同じ）
dayLabelClock.now = () => new Date("2026-11-09T10:00:00+09:00");
