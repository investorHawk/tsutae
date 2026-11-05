// @vitest-environment node
/**
 * ホーム画面に置いたときのアイコンと開き方（manifest・index.html）の約束。
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

  it("Service Worker は登録しない（オフライン動作は範囲外）", () => {
    expect(indexHtml).not.toContain("serviceWorker");
    expect(fs.existsSync(inPublic("sw.js"))).toBe(false);
  });
});
