import { useMemo } from "react";
import ErrorNote from "../ErrorNote";
import { describeRegimenError } from "../errors";
import { useDoctorApiError } from "../useDoctorApiError";
import RegimenBar from "./RegimenBar";
import RegimenChat from "./RegimenChat";
import RegimenConfirm from "./RegimenConfirm";
import RegimenDone from "./RegimenDone";
import RegimenFormView from "./RegimenFormView";
import RegimenLegend from "./RegimenLegend";
import RegimenTabs from "./RegimenTabs";
import { aiRowCountOf } from "./aiRows";
import {
  RegimenFormContext,
  type RegimenFormContextValue,
} from "./formContext";
import { regimenTabs } from "./tabList";
import { useRegimenScreen, type RegimenView } from "./useRegimenScreen";
import type { RegimenDraft } from "../../../api/regimenTypes";
import "./regimen.css";
import "./regimen-panels.css";

function headingOf(draft: RegimenDraft, view: RegimenView): string {
  const name = draft.form.basic.display_name ?? "新しいレジメン";
  const existing = draft.base_version !== null;
  if (view === "confirm") {
    return existing
      ? `確認: ${name}（版 ${draft.base_version} → 版 ${draft.version}）`
      : `確認: ${name}（新規・版 ${draft.version}）`;
  }
  return existing
    ? `${name}（版 ${draft.version} の下書き）`
    : `${name}（下書き・新規）`;
}

function statusOf(draft: RegimenDraft, view: RegimenView): string {
  if (view === "confirm") {
    return "採用の前の確認";
  }
  return draft.base_version !== null
    ? `下書き（採用するまで患者の画面は版 ${draft.base_version} のまま）`
    : "下書き（まだ患者に出ない）";
}

/**
 * D4 レジメン（v1.1。spec 9.1）: 左のフォーム（正本）＋右の Claude とのチャット。
 * タブでレジメンを開くと版 N+1 の下書き（新規は版1）になり、確認 → 採用で登録する。
 */
export default function RegimenSettings() {
  const handleError = useDoctorApiError();
  const screen = useRegimenScreen(handleError);
  const { catalog, editor, confirm, view } = screen;
  const draft = editor.draft;
  const tabs = useMemo(
    () => regimenTabs(catalog.regimens, catalog.drafts),
    [catalog.regimens, catalog.drafts],
  );
  const working = editor.working;
  // 別の下書きを開いている間（タブの切り替え中）も、今の下書きの操作を止める
  const busy = working || editor.loading;
  const { ask, patch } = screen;
  const context = useMemo<RegimenFormContextValue | null>(
    () =>
      draft
        ? {
            draft,
            ask,
            locked: busy,
            fieldErrors: editor.fieldErrors,
            drugNames: screen.drugNames,
            commit: (fieldId, value) =>
              patch({ changes: [{ field_id: fieldId, value }] }, [fieldId]),
            patch,
            setFieldError: editor.setFieldError,
          }
        : null,
    [
      draft,
      ask,
      busy,
      editor.fieldErrors,
      screen.drugNames,
      patch,
      editor.setFieldError,
    ],
  );

  return (
    <div className="rf-screen">
      {catalog.error ? (
        <ErrorNote
          code={catalog.error}
          prefix="レジメンの一覧を読み込めません"
        />
      ) : null}
      <RegimenTabs
        tabs={tabs}
        selected={screen.selected}
        hasPanel={draft !== null && screen.adopted === null}
        disabled={
          working || editor.loading || confirm.loading || confirm.adopting
        }
        onPick={(tab) => void screen.pick(tab)}
      />
      {screen.note ? (
        <p className="rf-notice" role="status">
          {screen.note}
        </p>
      ) : null}
      {editor.error ? (
        <ErrorNote code={editor.error} describe={describeRegimenError} />
      ) : null}
      {screen.adopted ? (
        <RegimenDone adopted={screen.adopted} onBack={screen.backToList} />
      ) : draft && context ? (
        <div
          className="rf-layout"
          id="rf-panel"
          role="tabpanel"
          aria-labelledby={
            screen.selected ? `rf-tab-${screen.selected}` : undefined
          }
        >
          <div className="rf-main">
            <div className="rf-heading">
              <h2>{headingOf(draft, view)}</h2>
              <span
                className={
                  draft.base_version !== null
                    ? "rf-status rf-status--existing"
                    : "rf-status"
                }
              >
                {statusOf(draft, view)}
              </span>
            </div>
            <RegimenFormContext.Provider value={context}>
              {view === "confirm" ? (
                <RegimenConfirm
                  draft={draft}
                  confirm={confirm}
                  editorBusy={busy}
                  ask={ask}
                  onDeleteValue={screen.deleteValue}
                  onBack={screen.backToForm}
                  onDiscard={screen.discard}
                  onAdopt={screen.adopt}
                />
              ) : (
                <>
                  <RegimenLegend />
                  <RegimenFormView handleError={handleError} />
                  <RegimenBar
                    draft={draft}
                    ask={ask}
                    busy={busy}
                    aiCount={aiRowCountOf(draft.sources)}
                    onConfirm={() => void screen.goConfirm()}
                    onDiscard={screen.discard}
                  />
                </>
              )}
            </RegimenFormContext.Provider>
          </div>
          <RegimenChat
            draft={draft}
            busy={busy}
            blocked={editor.blocked}
            notice={editor.notice}
            drugNames={screen.drugNames}
            onSend={screen.sendTurn}
            onJump={screen.jump}
          />
        </div>
      ) : editor.loading ? (
        <p className="d-muted">下書きを開いています…</p>
      ) : (
        <p className="d-muted rf-guide">
          上のタブでレジメンを開くか、「＋
          新しいレジメン」で作ります。既存のレジメンを開くと版 N+1
          の下書きになり、採用するまで患者の画面は変わりません。
        </p>
      )}
    </div>
  );
}
