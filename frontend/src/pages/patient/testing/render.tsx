/** 患者画面のテスト用の描画。実物の定型文と MemoryRouter で包む。 */
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { StaticPatientStringsProvider } from "../../../strings/PatientStrings";
import { STRINGS } from "./fixtures";

/** 今の経路を出す（画面遷移の確認用）。 */
export function Where() {
  const location = useLocation();
  return (
    <output
      data-testid="where"
      data-state={location.state === null ? "null" : "set"}
    >
      {location.pathname}
    </output>
  );
}

/** MemoryRouter の最初の場所（経路だけか、遷移時の state つき）。 */
export type InitialEntry = string | { pathname: string; state?: unknown };

export interface PageRoute {
  path: string;
  element: ReactElement;
}

/** routes を path に置いて initial から描く。/today 等の行き先は見出しだけの仮ページ。 */
export function renderPatient(
  routes: readonly PageRoute[],
  initial: InitialEntry,
): RenderResult {
  return render(
    <StaticPatientStringsProvider strings={STRINGS}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          {routes.map((r) => (
            <Route key={r.path} path={r.path} element={r.element} />
          ))}
        </Routes>
        <Where />
      </MemoryRouter>
    </StaticPatientStringsProvider>,
  );
}
