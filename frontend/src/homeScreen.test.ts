// @vitest-environment node
/**
 * ホーム画面に置いたときのアイコンと開き方（manifest・index.html）と、通知の sw.js の約束。
 */
import { beforeAll, describe, expect, it } from "vitest";

interface Fs {
  readFileSync(path: URL, encoding: "utf8"): string;
  readFileSync(path: URL): Uint8Array;
  existsSync(path: URL): boolean;
}

type Icon = { src: string; sizes: string; type: string; purpose?: string };
type Manifest = {
  name: string;
  short_name: string;
  lang: string;
  start_url: string;
  scope: string;
  display: string;
  theme_color: string;
  background_color: string;
  description?: string;
  icons: Icon[];
};

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
const inPublic = (name: string) =>
  new URL(`../public/${name.replace(/^\//, "")}`, import.meta.url);

let fs: Fs;
let manifest: Manifest;
let indexHtml = "";
let patientCss = "";

/** PNG の IHDR から幅と高さを読む。PNG でなければ例外。 */
function pngSize(name: string): { width: number; height: number } {
  const bytes = fs.readFileSync(inPublic(name));
  if (PNG_SIGNATURE.some((b, i) => bytes[i] !== b)) {
    throw new Error(`${name} は PNG でない`);
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return { width: view.getUint32(16), height: view.getUint32(20) };
}

beforeAll(async () => {
  // tsconfig の types に node が無いため、型は必要な分だけ書く（patientCss.test.ts と同じ）
  fs = (await import(/* @vite-ignore */ `node:${"fs"}`)) as Fs;
  manifest = JSON.parse(
    fs.readFileSync(inPublic("manifest.webmanifest"), "utf8"),
  ) as Manifest;
  indexHtml = fs.readFileSync(
    new URL("../index.html", import.meta.url),
    "utf8",
  );
  patientCss = fs.readFileSync(
    new URL("./styles/patient.css", import.meta.url),
    "utf8",
  );
});

describe("manifest.webmanifest", () => {
  it("全画面で開き、患者の今日の記録から始まる", () => {
    expect(manifest.display).toBe("standalone");
    expect(manifest.start_url).toBe("/today");
    expect(manifest.scope).toBe("/");
  });

  it("名前は「つたえ」で、説明文を持たない", () => {
    expect(manifest.name).toBe("つたえ");
    expect(manifest.short_name).toBe("つたえ");
    expect(manifest.lang).toBe("ja");
    expect(manifest.description).toBeUndefined();
  });

  it("色は患者画面の主色と地の色にそろえる", () => {
    expect(patientCss).toContain(`--p-primary: ${manifest.theme_color};`);
    expect(patientCss).toContain(`--p-bg: ${manifest.background_color};`);
  });

  it("192・512 の通常のアイコンと 512 のマスク用がある", () => {
    const keys = manifest.icons.map((i) => `${i.sizes}:${i.purpose ?? "any"}`);
    expect(keys).toEqual(
      expect.arrayContaining([
        "192x192:any",
        "512x512:any",
        "512x512:maskable",
      ]),
    );
  });

  it("書いた大きさの PNG が実際に置かれている", () => {
    for (const icon of manifest.icons) {
      const size = pngSize(icon.src);
      expect(icon.type).toBe("image/png");
      expect(`${size.width}x${size.height}`, icon.src).toBe(icon.sizes);
    }
  });
});

describe("index.html", () => {
  it("manifest を指す", () => {
    expect(indexHtml).toContain(
      '<link rel="manifest" href="/manifest.webmanifest" />',
    );
  });

  it("iPhone のホーム画面用の指定がある", () => {
    expect(indexHtml).toContain(
      '<link rel="apple-touch-icon" href="/apple-touch-icon.png" />',
    );
    expect(indexHtml).toContain(
      '<meta name="apple-mobile-web-app-capable" content="yes" />',
    );
    expect(indexHtml).toContain(
      '<meta name="apple-mobile-web-app-title" content="つたえ" />',
    );
  });

  it("テーマの色は manifest と同じ", () => {
    expect(indexHtml).toContain(
      `<meta name="theme-color" content="${manifest.theme_color}" />`,
    );
  });

  it("参照するアイコンが public にある", () => {
    expect(pngSize("apple-touch-icon.png")).toEqual({
      width: 180,
      height: 180,
    });
    expect(pngSize("favicon-32.png")).toEqual({ width: 32, height: 32 });
    expect(indexHtml).toContain('href="/favicon-32.png"');
    expect(indexHtml).toContain('href="/icon.svg"');
    expect(fs.existsSync(inPublic("icon.svg"))).toBe(true);
  });

  it("アイコンは文字を使わず、空色の地に紺の目と口の吹き出しで描く", () => {
    const svg = fs.readFileSync(inPublic("icon.svg"), "utf8");
    expect(svg).not.toContain("<text");
    expect(svg).toContain('stop-color="#3aa8f3"');
    expect(svg).toContain('stop-color="#1484de"');
    expect(svg).toContain(`fill="${manifest.theme_color}"`);
    expect(svg).toContain(`stroke="${manifest.theme_color}"`);
  });

  it("Service Worker は開いただけでは登録しない（登録は設定でオンにしたときだけ）", () => {
    expect(indexHtml).not.toContain("serviceWorker");
  });
});

describe("sw.js", () => {
  let sw = "";

  beforeAll(() => {
    sw = fs.readFileSync(inPublic("sw.js"), "utf8");
  });

  it("sw.js は通知専用で fetch を扱わない（オフライン動作は範囲外）", () => {
    expect(sw).not.toContain("fetch");
    expect(sw).not.toContain("caches");
  });

  it("push は waitUntil の中で必ず通知を出す", () => {
    expect(sw).toContain('addEventListener("push"');
    expect(sw).toContain("event.waitUntil(");
    expect(sw).toContain("showNotification(");
  });

  it("通知を押したら /today を開く", () => {
    expect(sw).toContain('addEventListener("notificationclick"');
    expect(sw).toContain('"/today"');
    expect(sw).toContain("openWindow(");
    expect(sw).toContain(".focus()");
  });

  it("予備のタイトルは定型文の notify.title と同じ（本文の文は持たない）", () => {
    const strings = JSON.parse(
      fs.readFileSync(
        new URL("../../backend/tsutae/patient_strings.json", import.meta.url),
        "utf8",
      ),
    ) as Record<string, string>;
    expect(sw).toContain(`FALLBACK_TITLE = "${strings["notify.title"]}"`);
    expect(sw).not.toContain(strings["notify.body"]);
  });
});
