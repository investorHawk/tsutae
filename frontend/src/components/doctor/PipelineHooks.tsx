import type { HookSummary } from "./pipelineEvents";

/** H1〜H4 のタイル。発火すれば色が付き、拒否があれば赤。 */
export default function PipelineHooks({ hooks }: { hooks: HookSummary[] }) {
  return (
    <section className="d-pl-hooks" aria-label="Hook">
      {hooks.map((hook) => {
        const state =
          hook.denied > 0 ? "deny" : hook.fired > 0 ? "fired" : "idle";
        return (
          <div
            key={hook.hookId}
            role="group"
            aria-label={`${hook.hookId} ${hook.label}`}
            className={`d-pl-hook d-pl-hook--${state}`}
          >
            <span className="d-pl-hook-id">{hook.hookId}</span>
            <span className="d-pl-hook-label">{hook.label}</span>
            <span className="d-pl-hook-count">
              発火 {hook.fired} ・ 拒否 {hook.denied}
            </span>
          </div>
        );
      })}
    </section>
  );
}
