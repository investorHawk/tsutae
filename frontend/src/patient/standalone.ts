/**
 * ホーム画面の外で開いているかの判定（docs/plan-device-records.md §5.8）。文面は持たない。
 * iPhone の Safari とホーム画面アプリは保存先が別で、Safari に置いた記録はアプリから見えないので、
 * Safari では記録させず「ホーム画面に追加」の案内だけを出す。
 * Android のブラウザは保存先が同じと見込み、記録を許して追加を勧める（実機で未確認）。
 */

export interface DisplayEnv {
  userAgent: string;
  maxTouchPoints: number;
  /** iPhone・iPad だけにある navigator.standalone */
  navigatorStandalone: boolean | undefined;
  /** CSS の display-mode: standalone */
  displayModeStandalone: boolean;
}

/** iPad は Mac の UA を名乗ることがある（Mac はタッチ点が 1 以下）。 */
function isAppleMobile(env: DisplayEnv): boolean {
  return (
    /iPhone|iPad|iPod/.test(env.userAgent) ||
    (/Macintosh/.test(env.userAgent) && env.maxTouchPoints > 1)
  );
}

function isStandalone(env: DisplayEnv): boolean {
  return env.navigatorStandalone === true || env.displayModeStandalone;
}

/** iPhone・iPad でホーム画面の外なら true（案内だけを出す）。 */
export function needsHomeScreenGuide(env: DisplayEnv): boolean {
  return isAppleMobile(env) && !isStandalone(env);
}

/** Android のブラウザなら true（画面は使え、追加を勧める）。 */
export function suggestsHomeScreen(env: DisplayEnv): boolean {
  return /Android/.test(env.userAgent) && !isStandalone(env);
}

/** 今の端末の値を読む。matchMedia が無い環境は standalone でないと見なす。 */
export function readDisplayEnv(): DisplayEnv {
  const { userAgent, maxTouchPoints } = navigator;
  const { standalone } = navigator as Navigator & { standalone?: boolean };
  return {
    userAgent,
    maxTouchPoints,
    navigatorStandalone: standalone,
    displayModeStandalone:
      window.matchMedia?.("(display-mode: standalone)").matches === true,
  };
}
