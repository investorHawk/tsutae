import { moveTabFocus } from "../tabKeys";
import type { RegimenTab } from "./tabList";

interface RegimenTabsProps {
  tabs: readonly RegimenTab[];
  selected: string | null;
  /** 選んだタブの中身（下書き）が出ているか（aria-controls を付ける） */
  hasPanel: boolean;
  disabled: boolean;
  onPick: (tab: RegimenTab) => void;
}

/**
 * レジメンのタブ（FOLFOX 版1 | CAPOX 版1 | ＋ 新しいレジメン）。Tab キーで入るのは選んだ
 * タブ（無ければ先頭）だけで、←→・Home・End で移る。開くのは Enter・Space・クリック
 * （開くと下書きを作るので、focus を移しただけでは開かない）。
 */
export default function RegimenTabs({
  tabs,
  selected,
  hasPanel,
  disabled,
  onPick,
}: RegimenTabsProps) {
  const focusKey = tabs.some((t) => t.key === selected)
    ? selected
    : (tabs[0]?.key ?? null);
  return (
    <div
      className="rf-tabs"
      role="tablist"
      aria-label="レジメン"
      onKeyDown={moveTabFocus}
    >
      {tabs.map((tab) => {
        const on = tab.key === selected;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            id={`rf-tab-${tab.key}`}
            aria-selected={on}
            aria-controls={on && hasPanel ? "rf-panel" : undefined}
            tabIndex={tab.key === focusKey ? 0 : -1}
            className={on ? "rf-tab rf-tab--on" : "rf-tab"}
            disabled={disabled}
            onClick={() => onPick(tab)}
          >
            {tab.label}
            {tab.sub ? <span className="rf-tab-sub"> {tab.sub}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
