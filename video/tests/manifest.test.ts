import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { FOOTAGE, FOOTAGE_IDS, footageTargetPath } from "../src/footage";
import {
  footageFiles,
  screenFiles,
  voiceFiles,
} from "../src/footage.generated";
import { voiceKeyOf } from "../src/lib/voice";
import { scenesB } from "../src/storyboards";

describe("撮影リストと manifest", () => {
  it("撮影リストは F1〜F11 の 11 本", () => {
    expect(FOOTAGE_IDS).toEqual([
      "F1",
      "F2",
      "F3",
      "F4",
      "F5",
      "F6",
      "F7",
      "F8",
      "F9",
      "F10",
      "F11",
    ]);
    for (const id of FOOTAGE_IDS) expect(FOOTAGE[id].id).toBe(id);
  });

  it("F11 はスマホの通知の静止画で、置き場所は public/screens/F11-1.png", () => {
    expect(FOOTAGE.F11).toMatchObject({
      slug: "patient_reminder",
      scene: "毎日のお知らせ",
      device: "phone",
      minSeconds: 5,
    });
    expect(FOOTAGE.F11.content).toContain("今日の記録をお願いします。");
    expect(footageTargetPath("F11")).toBe("video/public/screens/F11-1.png");
    expect(footageTargetPath("F1")).toBe("video/public/footage/F1.mp4");
  });

  it("先生の写真の置き場所は git の管理外", () => {
    const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
    const ignored = readFileSync(join(repoRoot, ".gitignore"), "utf8");
    expect(ignored.split("\n")).toContain("video/public/private/");
  });

  it("manifest は写真があれば portraitFile に載せ、無ければ null にする", () => {
    const script = join(
      dirname(fileURLToPath(import.meta.url)),
      "..",
      "scripts",
      "footage-manifest.mjs",
    );
    const root = mkdtempSync(join(tmpdir(), "tsutae-manifest-"));
    const generated = () => {
      execFileSync(process.execPath, [
        join(root, "scripts", "footage-manifest.mjs"),
      ]);
      return readFileSync(join(root, "src", "footage.generated.ts"), "utf8");
    };
    try {
      for (const dir of ["scripts", "src", "public/private"]) {
        mkdirSync(join(root, dir), { recursive: true });
      }
      copyFileSync(script, join(root, "scripts", "footage-manifest.mjs"));
      expect(generated()).toContain("portraitFile: string | null = null");
      writeFileSync(join(root, "public", "private", "portrait.jpg"), "");
      expect(generated()).toContain(
        'portraitFile: string | null = "private/portrait.jpg"',
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("manifest の生成は撮影リストの全ての id の静止画を拾う（空のファイルを一時フォルダで）", () => {
    const script = join(
      dirname(fileURLToPath(import.meta.url)),
      "..",
      "scripts",
      "footage-manifest.mjs",
    );
    const root = mkdtempSync(join(tmpdir(), "tsutae-manifest-"));
    try {
      for (const dir of ["scripts", "src", "public/screens"]) {
        mkdirSync(join(root, dir), { recursive: true });
      }
      copyFileSync(script, join(root, "scripts", "footage-manifest.mjs"));
      for (const id of FOOTAGE_IDS) {
        writeFileSync(join(root, "public", "screens", `${id}-1.png`), "");
      }
      execFileSync(process.execPath, [
        join(root, "scripts", "footage-manifest.mjs"),
      ]);
      const generated = readFileSync(
        join(root, "src", "footage.generated.ts"),
        "utf8",
      );
      for (const id of FOOTAGE_IDS) {
        expect(generated, id).toContain(`${id}: ["screens/${id}-1.png"]`);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("manifest の録画は既知の id で public/footage の下を指す", () => {
    for (const [id, path] of Object.entries(footageFiles)) {
      expect(FOOTAGE_IDS).toContain(id);
      expect(path).toMatch(/^footage\/F\d+([_-].*)?\.(mp4|mov)$/i);
    }
  });

  it("manifest の静止画は既知の id で public/screens/F<n>-<k>.png を k の順に指す", () => {
    for (const [id, paths] of Object.entries(screenFiles)) {
      expect(FOOTAGE_IDS).toContain(id);
      expect(paths?.length, id).toBeGreaterThan(0);
      const ks = (paths ?? []).map((p) => {
        const m = /^screens\/(F\d+)-(\d+)\.png$/.exec(p);
        expect(m, p).not.toBeNull();
        expect(m?.[1], p).toBe(id);
        return Number(m?.[2]);
      });
      expect(ks).toEqual([...ks].sort((a, b) => a - b));
    }
  });

  it("撮影済みの静止画（F1・F2・F4・F8・F9）が manifest に載る", () => {
    expect(screenFiles.F1).toEqual(["screens/F1-1.png", "screens/F1-2.png"]);
    expect(screenFiles.F2).toEqual([
      "screens/F2-1.png",
      "screens/F2-2.png",
      "screens/F2-3.png",
    ]);
    expect(screenFiles.F4).toHaveLength(2);
    expect(screenFiles.F8).toHaveLength(3);
    expect(screenFiles.F9).toEqual(["screens/F9-1.png"]);
  });

  it("manifest の声は voice/ の下で、キーが案 B の場面 id の頭のどれか（0 本でもよい）", () => {
    const keys = scenesB.map((s) => voiceKeyOf(s.id));
    for (const [key, path] of Object.entries(voiceFiles)) {
      expect(keys, key).toContain(key);
      expect(path, key).toMatch(
        new RegExp(`^voice/${key}([_-][^/]*)?\\.(m4a|mp3|wav)$`, "i"),
      );
    }
  });
});
