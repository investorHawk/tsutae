import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import type { Parsed } from "./fieldValues";
import { domIdOf } from "./fieldLabels";
import { fieldStateOf, showsStateTag, stateTagOf } from "./fieldState";
import { useRegimenForm } from "./formContext";

interface FieldShellProps {
  fieldId: string;
  label: string;
  /** 表のセルでは見出しが列にあるので、名前は読み上げだけにする */
  hideLabel?: boolean;
  children: (props: {
    id: string;
    describedBy: string | undefined;
    invalid: boolean;
  }) => ReactNode;
  /** 欄の外で出す理由（入力の文字を読めなかった等） */
  className?: string;
}

/** 欄の枠: 名前・状態の札（ai と doc は読み上げだけ。showsStateTag）・欄の下の理由。 */
export function FieldShell({
  fieldId,
  label,
  hideLabel = false,
  children,
  className = "",
}: FieldShellProps) {
  const { draft, ask, fieldErrors } = useRegimenForm();
  const state = fieldStateOf(draft, fieldId, ask);
  const tag = stateTagOf(state, draft.sources[fieldId]);
  const errors = fieldErrors[fieldId] ?? [];
  const id = domIdOf(fieldId);
  const tagId = tag ? `${id}-tag` : "";
  const errId = errors.length > 0 ? `${id}-err` : "";
  const describedBy = [tagId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div
      className={`rf-field rf-field--${state} ${className}`.trim()}
      data-field-id={fieldId}
      data-state={state}
    >
      <label
        htmlFor={id}
        className={hideLabel ? "rf-sr-only" : "rf-field-label"}
      >
        {label}
      </label>
      {children({ id, describedBy, invalid: errors.length > 0 })}
      {tag ? (
        <span
          id={tagId}
          className={showsStateTag(state) ? "rf-tag" : "rf-sr-only"}
        >
          {tag}
        </span>
      ) : null}
      {errors.length > 0 ? (
        <span id={errId} className="rf-field-error" role="alert">
          {errors.join("／")}
        </span>
      ) : null}
    </div>
  );
}

interface FieldInputProps {
  fieldId: string;
  label: string;
  /** 今の値を入力の文字にしたもの */
  value: string;
  parse: (text: string) => Parsed<unknown>;
  multiline?: boolean;
  inputMode?: "numeric" | "text";
  placeholder?: string;
  disabled?: boolean;
  hideLabel?: boolean;
  maxLength?: number;
  /** 入力の候補の datalist の id（1行の欄だけ。候補に無い値も書ける） */
  list?: string;
}

/**
 * 文字の欄。入力のたびには送らず、欄を離れたとき（と 1行の欄の Enter）に値に直して
 * PATCH する。読めない入力は送らずに理由を出す。サーバーの値が変われば表示も揃えるが、
 * 送った後に書き足している途中（focus 中で未送信の入力がある）・送っている途中は上書き
 * しない。送っている値と同じなら2回は送らない（Enter の後の blur）。
 */
export function FieldInput({
  fieldId,
  label,
  value,
  parse,
  multiline = false,
  inputMode = "text",
  placeholder,
  disabled = false,
  hideLabel = false,
  maxLength,
  list,
}: FieldInputProps) {
  const { locked, commit, setFieldError } = useRegimenForm();
  const [text, setText] = useState(value);
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  /** 最後に揃えた・送った後に書き換えた（まだ送っていない） */
  const dirty = useRef(false);
  /** 送っている途中の文字（返事が来るまで） */
  const pending = useRef<string | null>(null);
  const latest = useRef(value);
  latest.current = value;

  useEffect(() => {
    const focused =
      ref.current !== null && document.activeElement === ref.current;
    if ((focused && dirty.current) || pending.current !== null) {
      return;
    }
    dirty.current = false;
    setText(value);
  }, [value]);

  function change(next: string) {
    dirty.current = true;
    setText(next);
  }

  function save() {
    if (!dirty.current || text === pending.current) {
      return;
    }
    if (text === value) {
      dirty.current = false;
      setFieldError(fieldId, null);
      return;
    }
    const parsed = parse(text);
    if (!parsed.ok) {
      setFieldError(fieldId, parsed.message);
      return;
    }
    const sent = text;
    dirty.current = false;
    pending.current = sent;
    void commit(fieldId, parsed.value).then((ok) => {
      if (pending.current !== sent) {
        return;
      }
      pending.current = null;
      if (!ok) {
        // 保存できなかった文字は「未送信」に戻す（欄を離れれば送り直す）
        dirty.current = true;
      } else if (!dirty.current) {
        // 返事の描き直しが先だったときも、サーバーの値（整えた形）に揃える
        setText(latest.current);
      }
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (
      event.key === "Enter" &&
      !event.nativeEvent.isComposing &&
      event.keyCode !== 229
    ) {
      event.preventDefault();
      save();
    }
  }

  return (
    <FieldShell fieldId={fieldId} label={label} hideLabel={hideLabel}>
      {({ id, describedBy, invalid }) =>
        multiline ? (
          <textarea
            ref={ref}
            id={id}
            value={text}
            placeholder={placeholder}
            disabled={disabled || locked}
            maxLength={maxLength}
            aria-describedby={describedBy}
            aria-invalid={invalid || undefined}
            onChange={(e) => change(e.target.value)}
            onBlur={save}
          />
        ) : (
          <input
            ref={ref}
            id={id}
            type="text"
            inputMode={inputMode}
            list={list}
            value={text}
            placeholder={placeholder}
            disabled={disabled || locked}
            maxLength={maxLength}
            aria-describedby={describedBy}
            aria-invalid={invalid || undefined}
            onChange={(e) => change(e.target.value)}
            onBlur={save}
            onKeyDown={onKeyDown}
          />
        )
      }
    </FieldShell>
  );
}

interface FieldSelectProps {
  fieldId: string;
  label: string;
  value: string;
  options: readonly { value: string; label: string }[];
  /** 選んだ文字 → 送る値 */
  toValue: (selected: string) => unknown;
  disabled?: boolean;
  hideLabel?: boolean;
}

/** 選ぶ欄（経路・対応する質問など）。選んだらすぐ送る。 */
export function FieldSelect({
  fieldId,
  label,
  value,
  options,
  toValue,
  disabled = false,
  hideLabel = false,
}: FieldSelectProps) {
  const { locked, commit } = useRegimenForm();
  return (
    <FieldShell fieldId={fieldId} label={label} hideLabel={hideLabel}>
      {({ id, describedBy, invalid }) => (
        <select
          id={id}
          value={value}
          disabled={disabled || locked}
          aria-describedby={describedBy}
          aria-invalid={invalid || undefined}
          onChange={(e) => void commit(fieldId, toValue(e.target.value))}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </FieldShell>
  );
}
