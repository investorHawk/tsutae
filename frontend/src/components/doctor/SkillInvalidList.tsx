import type { InvalidSkill } from "../../api/types";

const CODE_LABELS: Readonly<Record<string, string>> = {
  missing: "SKILL.md がありません",
  format: "frontmatter を読めません",
  schema: "frontmatter の項目が合いません",
  name_mismatch: "frontmatter の name とディレクトリ名が違います",
  too_large: "SKILL.md が大きすぎます",
};

function describeSkillError(code: string): string {
  return CODE_LABELS[code] ?? "読み込めません";
}

/**
 * D4: 読めない Skill（GET skills の invalid。W3 後の決定）。壊れていても医師画面は止めず、
 * ここに出す。必須の Skill（regimen の2本・report-format-default）が読めない間は、
 * その Skill を使う記録・レポートが作れない。
 */
export default function SkillInvalidList({
  items,
}: {
  items: readonly InvalidSkill[];
}) {
  if (items.length === 0) {
    return null;
  }
  const required = items.some((item) => item.required);
  return (
    <section
      role="alert"
      className="d-error d-skill-invalid"
      aria-label="読めない Skill"
    >
      <p>
        読めない Skill が {items.length} 件あります。SKILL.md を直してください。
        {required
          ? "必須の Skill が直るまで、それを使う記録の画面・レポートは作れません。"
          : ""}
      </p>
      <ul>
        {items.map((item) => (
          <li key={item.name}>
            <code>{item.name}</code>
            {item.required ? (
              <span className="d-badge d-badge--warn">必須</span>
            ) : null}
            ：{describeSkillError(item.error_code)}（
            <code>{item.error_code}</code>）
          </li>
        ))}
      </ul>
    </section>
  );
}
