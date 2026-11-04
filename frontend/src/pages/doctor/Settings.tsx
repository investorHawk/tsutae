import { useState } from "react";
import RegimenSettings from "../../components/doctor/regimen/RegimenSettings";
import { moveTabFocus } from "../../components/doctor/tabKeys";
import ReportFormatSettings from "./ReportFormatSettings";
import "../../components/doctor/doctor-ui.css";
import "../../components/doctor/settings.css";

type SettingsTab = "regimen" | "report-format";

const TABS: readonly { key: SettingsTab; label: string }[] = [
  { key: "regimen", label: "レジメン" },
  { key: "report-format", label: "レポートの形式（一文で頼む）" },
];

function Panel({ tab }: { tab: SettingsTab }) {
  return tab === "regimen" ? <RegimenSettings /> : <ReportFormatSettings />;
}

/**
 * D4 設定を変える（v1.1）。「レジメン」はフォーム＋チャット（spec 9.1）、
 * 「レポートの形式」は旧 D4 の一文 → 差分 → 承認（spec 9.2。report-format-* だけ）。
 * 一度開いた種類は描いたまま隠す（Claude の往復の最中・欄に入れている途中で種類を
 * 替えても、下書きの画面の状態・返ってきた往復の結果を失わない）。
 */
export default function Settings() {
  const [tab, setTab] = useState<SettingsTab>("regimen");
  const [opened, setOpened] = useState<readonly SettingsTab[]>(["regimen"]);

  function choose(next: SettingsTab) {
    setTab(next);
    setOpened((prev) => (prev.includes(next) ? prev : [...prev, next]));
  }

  return (
    <section className="page">
      <h1>設定を変える</h1>
      <div
        className="rf-kind-tabs"
        role="tablist"
        aria-label="設定の種類"
        onKeyDown={moveTabFocus}
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`settings-tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls={
              opened.includes(t.key) ? `settings-panel-${t.key}` : undefined
            }
            tabIndex={tab === t.key ? 0 : -1}
            className={
              tab === t.key ? "rf-kind-tab rf-kind-tab--on" : "rf-kind-tab"
            }
            onClick={() => choose(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {TABS.filter((t) => opened.includes(t.key)).map((t) => (
        <div
          key={t.key}
          id={`settings-panel-${t.key}`}
          role="tabpanel"
          aria-labelledby={`settings-tab-${t.key}`}
          hidden={tab !== t.key}
        >
          <Panel tab={t.key} />
        </div>
      ))}
    </section>
  );
}
