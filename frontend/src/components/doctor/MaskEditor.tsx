import { useId, useRef, useState } from "react";
import { selectionSpan } from "./maskSelection";
import { addSpan, removeSpanAt, splitByMasks, type Span } from "./maskSpans";

interface MaskEditorProps {
  text: string;
  spans: Span[];
  onChange: (spans: Span[]) => void;
}

/**
 * 送る前に伏せる所（D6）。伏せた区間は黒い「伏せ字」の印（button）で、押すと元の文字に
 * 戻す（キーボードでも押せる）。ほかの所はマウスで選んで「伏せ字にする」で足す。選んだ
 * 範囲が伏せた区間と重なる・隣り合うときは1つにまとめる（伏せた区間の中だけを選んでも
 * 変わらない）。医師は文を書かない（区間だけを選ぶ）。
 */
export default function MaskEditor({ text, spans, onChange }: MaskEditorProps) {
  const ref = useRef<HTMLDivElement>(null);
  const labelId = useId();
  const [hint, setHint] = useState<string | null>(null);
  const length = Array.from(text).length;

  function maskSelection() {
    const span = ref.current
      ? selectionSpan(ref.current, window.getSelection(), length)
      : null;
    if (span === null) {
      setHint("伏せる文字を、下の文からマウスで選んでから押してください");
      return;
    }
    setHint(null);
    window.getSelection()?.removeAllRanges();
    onChange(addSpan(spans, span));
  }

  return (
    <div className="d-mask-editor">
      <p className="d-mask-label" id={labelId}>
        送る前に伏せる所（黒い「伏せ字」は押すと元の文字に戻ります）
      </p>
      <div ref={ref} className="d-mask-text" aria-labelledby={labelId}>
        {splitByMasks(text, spans).map((piece) =>
          piece.masked ? (
            <button
              key={`m${piece.start}`}
              type="button"
              className="d-mask"
              data-start={piece.start}
              data-end={piece.end}
              aria-label={`伏せ字「${piece.text}」を戻す`}
              title="押すと元の文字に戻します"
              onClick={() => onChange(removeSpanAt(spans, piece.start))}
            >
              伏せ字
            </button>
          ) : (
            <span
              key={`t${piece.start}`}
              data-start={piece.start}
              data-end={piece.end}
            >
              {piece.text}
            </span>
          ),
        )}
      </div>
      <div className="d-actions">
        <button
          type="button"
          // 押した時に選択が外れないようにする
          onMouseDown={(e) => e.preventDefault()}
          onClick={maskSelection}
        >
          伏せ字にする
        </button>
      </div>
      {hint ? (
        <p className="d-muted" role="status">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
