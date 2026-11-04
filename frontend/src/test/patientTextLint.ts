/**
 * 患者画面のソースの直書き検査（docs/architecture.md §9「直書きしない。テストで検査」）。
 * TypeScript の構文木を歩き、患者に見える文字列が t(key)・API の値（式）・数字と記号の
 * ほかから出ていないかを見る。コメントは構文木に無いので自然に除かれる。
 *
 * 契約（docs/architecture.md §9 W2b の決定）の2規則は non-ascii（文字列リテラルに日本語を
 * 含めない）と jsx-text（JSX のテキストに英字を書かない）。jsx-literal・jsx-attr・ascii-prose は
 * それより強く見るための追加の規則。
 *
 * 規則（1つの文字列には最初に当たった1つだけを報告する）:
 * - jsx-text: JSX のテキストに英字か ASCII 以外の文字がある（数字・記号・空白だけ許す）
 * - non-ascii: 文字列・テンプレートに ASCII 以外の文字（日本語・全角）がある
 * - jsx-literal: JSX の子として描かれる位置（条件式・&&・配列・連結を通るものを含む）の
 *   文字列に英字がある。t(...) などの呼び出しの引数は描かれる位置ではない
 * - jsx-attr: 読み上げ・表示される属性（aria-label・placeholder・title・alt 等）の文字列に英字
 * - ascii-prose: 英単語が2つ以上並ぶ文字列（文面らしいもの）。console・Error の引数、
 *   import の経路、className は除く
 *
 * 限界: 1語の英字を変数に入れてから描くもの（const x = "Error"; <p>{x}</p>）は見逃す
 * （契約で「変数経由の英字は検査の外」。frontend/README.md に書いてある）。
 */
import ts from "typescript";

export type TextRule =
  | "jsx-text"
  | "non-ascii"
  | "jsx-literal"
  | "jsx-attr"
  | "ascii-prose";

export interface TextViolation {
  line: number;
  rule: TextRule;
  text: string;
}

const LETTER = /\p{L}/u;
// eslint-disable-next-line no-control-regex
const NON_ASCII = /[^\x00-\x7f]/;
const ASCII_PROSE = /[A-Za-z]{2,}\s+[A-Za-z]{2,}/;

const TEXT_ATTRS: ReadonlySet<string> = new Set([
  "aria-label",
  "aria-description",
  "aria-roledescription",
  "aria-placeholder",
  "aria-valuetext",
  "placeholder",
  "title",
  "alt",
  "label",
]);

type LiteralNode =
  | ts.StringLiteral
  | ts.NoSubstitutionTemplateLiteral
  | ts.TemplateHead
  | ts.TemplateMiddle
  | ts.TemplateTail;

function isLiteral(node: ts.Node): node is LiteralNode {
  return (
    ts.isStringLiteral(node) ||
    ts.isNoSubstitutionTemplateLiteral(node) ||
    node.kind === ts.SyntaxKind.TemplateHead ||
    node.kind === ts.SyntaxKind.TemplateMiddle ||
    node.kind === ts.SyntaxKind.TemplateTail
  );
}

function attrName(attr: ts.JsxAttribute): string {
  return attr.name.getText();
}

/** 子が親の中で「値として流れる」位置か（描かれる位置へ届くかを辿るのに使う）。 */
function passesValue(child: ts.Node, parent: ts.Node): boolean {
  if (
    ts.isParenthesizedExpression(parent) ||
    ts.isArrayLiteralExpression(parent) ||
    ts.isTemplateSpan(parent) ||
    ts.isTemplateExpression(parent)
  ) {
    return true;
  }
  if (ts.isConditionalExpression(parent)) {
    return child !== parent.condition;
  }
  if (ts.isBinaryExpression(parent)) {
    const op = parent.operatorToken.kind;
    if (op === ts.SyntaxKind.AmpersandAmpersandToken) {
      return child === parent.right;
    }
    return (
      op === ts.SyntaxKind.BarBarToken ||
      op === ts.SyntaxKind.QuestionQuestionToken ||
      op === ts.SyntaxKind.PlusToken
    );
  }
  return false;
}

/** 文字列が描かれる位置: JSX の子なら "child"、属性なら属性名。どちらでもなければ null。 */
function renderedAt(node: ts.Node): string | null {
  let child: ts.Node = node;
  let parent: ts.Node | undefined = node.parent;
  while (parent) {
    if (ts.isJsxAttribute(parent)) {
      return attrName(parent);
    }
    if (ts.isJsxExpression(parent)) {
      const owner = parent.parent;
      if (ts.isJsxAttribute(owner)) {
        return attrName(owner);
      }
      return ts.isJsxElement(owner) || ts.isJsxFragment(owner) ? "child" : null;
    }
    if (!passesValue(child, parent)) {
      return null;
    }
    child = parent;
    parent = parent.parent;
  }
  return null;
}

function isConsoleCall(expr: ts.Expression): boolean {
  return (
    ts.isPropertyAccessExpression(expr) &&
    ts.isIdentifier(expr.expression) &&
    expr.expression.text === "console"
  );
}

function isErrorNew(expr: ts.Expression): boolean {
  return ts.isIdentifier(expr) && /Error$/.test(expr.text);
}

/** console.*() / new XxxError() の引数、import の経路、className の中か。 */
function isProseExempt(node: ts.Node): boolean {
  for (let p: ts.Node | undefined = node.parent; p; p = p.parent) {
    if (ts.isCallExpression(p) && isConsoleCall(p.expression)) {
      return true;
    }
    if (ts.isNewExpression(p) && isErrorNew(p.expression)) {
      return true;
    }
    if (
      ts.isImportDeclaration(p) ||
      ts.isExportDeclaration(p) ||
      ts.isExternalModuleReference(p)
    ) {
      return true;
    }
    if (ts.isJsxAttribute(p)) {
      return attrName(p) === "className";
    }
  }
  return false;
}

function literalRule(node: LiteralNode): TextRule | null {
  const text = node.text;
  if (NON_ASCII.test(text)) {
    return "non-ascii";
  }
  const at = renderedAt(node);
  if (at === "child" && LETTER.test(text)) {
    return "jsx-literal";
  }
  if (at !== null && TEXT_ATTRS.has(at) && LETTER.test(text)) {
    return "jsx-attr";
  }
  if (ASCII_PROSE.test(text) && !isProseExempt(node)) {
    return "ascii-prose";
  }
  return null;
}

function jsxTextRule(node: ts.JsxText): TextRule | null {
  if (node.containsOnlyTriviaWhiteSpaces) {
    return null;
  }
  return LETTER.test(node.text) || NON_ASCII.test(node.text)
    ? "jsx-text"
    : null;
}

/** source の直書きを返す（無ければ空）。fileName の拡張子で .ts / .tsx を選ぶ。 */
export function findHardcodedText(
  source: string,
  fileName = "sample.tsx",
): TextViolation[] {
  const kind = fileName.endsWith(".ts") ? ts.ScriptKind.TS : ts.ScriptKind.TSX;
  const file = ts.createSourceFile(
    fileName,
    source,
    ts.ScriptTarget.Latest,
    true,
    kind,
  );
  const found: TextViolation[] = [];
  const visit = (node: ts.Node): void => {
    const rule = ts.isJsxText(node)
      ? jsxTextRule(node)
      : isLiteral(node)
        ? literalRule(node)
        : null;
    if (rule) {
      const { line } = file.getLineAndCharacterOfPosition(node.getStart(file));
      found.push({ line: line + 1, rule, text: node.getText(file).trim() });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

/**
 * 日本語・全角だけの検査（non-ascii と、ASCII 以外を含む jsx-text）。患者画面のテストに
 * 当て、期待値を s(key)・questionText() から引かせる（直書きの写しを作らせない）。
 */
export function findNonAsciiText(
  source: string,
  fileName = "sample.tsx",
): TextViolation[] {
  return findHardcodedText(source, fileName).filter(
    (v) =>
      v.rule === "non-ascii" ||
      (v.rule === "jsx-text" && NON_ASCII.test(v.text)),
  );
}
