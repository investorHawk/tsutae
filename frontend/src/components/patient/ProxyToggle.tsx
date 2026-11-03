import { usePatientStrings } from "../../strings/PatientStrings";

interface ProxyToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

/** 「家族が代わりに入力しています」（entry.by_proxy）。ラベル全体が押せる面。 */
export default function ProxyToggle({
  checked,
  onChange,
  disabled = false,
}: ProxyToggleProps) {
  const { t } = usePatientStrings();
  return (
    <label className="p-toggle">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {t("today.proxy_toggle")}
    </label>
  );
}
