import type { FormEvent } from "react";
import type { CourseFormValues } from "./courseValues";

interface CourseFormProps {
  values: CourseFormValues;
  busy: boolean;
  onChange: (values: CourseFormValues) => void;
  onSubmit: () => void;
  onCancelEdit: () => void;
}

type TextField = Exclude<keyof CourseFormValues, "id">;

/** D2 の実投与日の登録・修正フォーム。修正中はコース番号を変えられない。 */
export default function CourseForm({
  values,
  busy,
  onChange,
  onSubmit,
  onCancelEdit,
}: CourseFormProps) {
  const editing = values.id !== null;

  function field(name: TextField) {
    return {
      value: values[name],
      onChange: (e: { target: { value: string } }) =>
        onChange({ ...values, [name]: e.target.value }),
    };
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="d-course-form" onSubmit={handleSubmit} noValidate>
      <h2>{editing ? `第${values.course_no}コースを修正` : "コースを追加"}</h2>
      <div className="d-form-grid">
        <label className="d-field">
          <span>コース番号</span>
          <input
            type="number"
            min={1}
            step={1}
            readOnly={editing}
            {...field("course_no")}
          />
        </label>
        <label className="d-field">
          <span>実投与日（Day1）</span>
          <input type="date" required {...field("infusion_date")} />
        </label>
        <label className="d-field">
          <span>予定日（延期の注記に使う）</span>
          <input type="date" {...field("planned_date")} />
        </label>
        <label className="d-field">
          <span>次回受診予定日</span>
          <input type="date" {...field("next_visit")} />
        </label>
        <label className="d-field d-field--wide">
          <span>メモ</span>
          {/* maxLength は UTF-16 で数え、貼り付けを黙って切るので付けない（送る前に検査） */}
          <input type="text" {...field("note")} />
        </label>
      </div>
      <div className="d-actions">
        <button type="submit" className="d-primary" disabled={busy}>
          保存
        </button>
        {editing ? (
          <button type="button" onClick={onCancelEdit} disabled={busy}>
            修正をやめる
          </button>
        ) : null}
      </div>
      <p className="d-muted">
        延期があれば、実投与日を実際の日に直し、予定日に元の日を入れます。Day
        は実投与日から数え直します。
      </p>
    </form>
  );
}
