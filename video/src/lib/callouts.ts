// 録画の場面の札（callouts）をどの時点で出すか。React / remotion を import しない。

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

/**
 * 区間 segmentIndex の progress（区間の中の割合 0〜1）の時点で出す札。
 * 札は区間ごとに 1 つで、区間より札が多ければ最後の区間を札の数で均等に割って順に出す。
 * （F4 は静止画が 2 枚なので、札 2 つの切り替えは 2 枚目の静止画の頭に重なる）
 */
export const calloutAt = (
  callouts: readonly (string | null)[],
  segmentIndex: number,
  segmentCount: number,
  progress: number,
): string | null => {
  const isLast = segmentIndex === segmentCount - 1;
  const own = isLast
    ? callouts.slice(segmentIndex)
    : callouts.slice(segmentIndex, segmentIndex + 1);
  if (own.length === 0) return null;
  const at = Math.min(
    own.length - 1,
    Math.floor(clamp01(progress) * own.length),
  );
  return own[at] ?? null;
};
