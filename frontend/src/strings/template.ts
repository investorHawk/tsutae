/**
 * 定型文の中の {name} を値で埋める（例 history.date の {month}・{day}・{weekday}）。
 * 文面は定型文の側にだけあり、ここは置き換えるだけ。値の無い名前はそのまま残す。
 * 置き換えは1回だけ（値の中の {x} はもう置き換えない）。
 */
const PLACEHOLDER = /\{([a-z_]+)\}/g;

export function fillTemplate(
  template: string,
  values: Readonly<Record<string, string | number>>,
): string {
  return template.replace(PLACEHOLDER, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name)
      ? String(values[name])
      : whole,
  );
}
