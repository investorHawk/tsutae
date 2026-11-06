import { Fragment } from "react";
import { boldSegments } from "./boldText";
import {
  replyBlocks,
  type ListBlock,
  type ReplyBlock,
  type TableBlock,
} from "./replyBlocks";
import "./reply.css";

/** 文の中の **…** だけを <strong> にする（HTML として読み込まない）。 */
function Inline({ text }: { text: string }) {
  return (
    <>
      {boldSegments(text).map((segment, n) =>
        segment.bold ? (
          <strong key={n}>{segment.text}</strong>
        ) : (
          <Fragment key={n}>{segment.text}</Fragment>
        ),
      )}
    </>
  );
}

function ReplyList({ list }: { list: ListBlock }) {
  const items = list.items.map((item, n) => (
    <li key={n}>
      <Inline text={item.text} />
      {item.children.map((child, m) => (
        <ReplyList key={m} list={child} />
      ))}
    </li>
  ));
  return list.ordered ? (
    <ol
      className="rf-reply-list"
      start={list.start === 1 ? undefined : list.start}
    >
      {items}
    </ol>
  ) : (
    <ul className="rf-reply-list">{items}</ul>
  );
}

function ReplyTable({ table }: { table: TableBlock }) {
  return (
    <table className="rf-reply-table">
      <thead>
        <tr>
          {table.header.map((cell, n) => (
            <th key={n} scope="col">
              <Inline text={cell} />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {table.rows.map((row, n) => (
          <tr key={n}>
            {row.map((cell, m) => (
              <td key={m}>
                <Inline text={cell} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Block({ block }: { block: ReplyBlock }) {
  if (block.kind === "list") {
    return <ReplyList list={block} />;
  }
  if (block.kind === "table") {
    return <ReplyTable table={block} />;
  }
  return (
    <p className="rf-reply-p">
      <Inline text={block.text} />
    </p>
  );
}

/**
 * Claude の返答の文（段落・箇条書き・番号付き・表・太字）。先生の文には使わない。
 * dangerouslySetInnerHTML も Markdown のライブラリも使わず、塊を React の要素で描く。
 */
export default function ReplyText({ text }: { text: string }) {
  return (
    <>
      {replyBlocks(text).map((block, n) => (
        <Block key={n} block={block} />
      ))}
    </>
  );
}
