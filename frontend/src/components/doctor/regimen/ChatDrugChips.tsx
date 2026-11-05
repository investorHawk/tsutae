interface ChatDrugChipsProps {
  names: readonly string[];
  disabled: boolean;
  onPick: (name: string) => void;
}

/** 入力欄の上の薬の候補。押すと入力欄に入る（送らない）。多いときは枠の中でスクロールする。 */
export default function ChatDrugChips({
  names,
  disabled,
  onPick,
}: ChatDrugChipsProps) {
  return (
    <div role="group" aria-labelledby="rf-drug-chips-h">
      <p id="rf-drug-chips-h" className="rf-drug-chips-h">
        薬の候補（押すと入ります）
      </p>
      <div className="rf-chips rf-drug-chips">
        {names.map((name) => (
          <button
            key={name}
            type="button"
            className="rf-flink"
            disabled={disabled}
            onClick={() => onPick(name)}
          >
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}
