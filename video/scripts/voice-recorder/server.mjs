// ナレーションの録音アプリ（このハッカソン専用）。npm run voice で起動する。
// 原稿と秒は src/storyboards/b.ts から読み、声は public/voice/b<nn>.wav に保存する。
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { VOICE_OFFSET_SECONDS, voiceKeyOf } from "../../src/lib/voice.ts";
import { scenesB } from "../../src/storyboards/b.ts";
import {
  isVoiceKey,
  keepTake,
  loadScriptEdits,
  parseRange,
  saveScriptEdit,
  saveVoice,
  savedVoice,
  wavSeconds,
} from "./store.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const VIDEO = resolve(HERE, "..", "..");
const VOICE_DIR = process.env.VOICE_DIR ?? join(VIDEO, "public", "voice");
const ARCHIVE_DIR =
  process.env.VOICE_ARCHIVE_DIR ?? join(VIDEO, "out", "voice");
// 聞き比べ用の音声。無ければ再生欄を出さない
const SAMPLE_DIR =
  process.env.VOICE_SAMPLE_DIR ??
  resolve(VIDEO, "../../Hackathon2026idea/voice_demo/v175/public/voice");
// 変更後の原稿。録音を終えたら b.ts へ移し、字幕とテストをそろえる
const EDITS_FILE =
  process.env.VOICE_EDITS_FILE ??
  resolve(VIDEO, "../docs/video/narration-b-edits.json");
const PORT = Number(process.env.PORT ?? 5199);
const MAX_BODY_BYTES = 64 * 1024 * 1024;
const MAX_CLIPBOARD_CHARS = 8000;

const STATIC_FILES = {
  "/": ["index.html", "text/html; charset=utf-8"],
  "/app.mjs": ["app.mjs", "text/javascript; charset=utf-8"],
  "/audio.mjs": ["audio.mjs", "text/javascript; charset=utf-8"],
  "/script.mjs": ["script.mjs", "text/javascript; charset=utf-8"],
  "/worklet.js": ["worklet.js", "text/javascript; charset=utf-8"],
};
const UNTITLED = { promises: "AI がしないこと", closing: "締め" };

const samplePath = (key) => join(SAMPLE_DIR, `${key}.wav`);

const sampleSeconds = (key) =>
  existsSync(samplePath(key))
    ? wavSeconds(readFileSync(samplePath(key)))
    : null;

/** 保存済みの声が、原稿を変える前に録ったものか */
const isVoiceOutdated = (saved, edit) =>
  Boolean(saved && edit) &&
  statSync(join(VOICE_DIR, saved.file)).mtime < new Date(edit.updatedAt);

const sceneList = () => {
  const edits = loadScriptEdits(EDITS_FILE);
  return scenesB.map((scene) => {
    const key = voiceKeyOf(scene.id);
    const saved = savedVoice(VOICE_DIR, key);
    const edit = edits[key];
    return {
      key,
      title: scene.title ?? UNTITLED[scene.kind] ?? scene.id,
      seconds: scene.seconds,
      budget: scene.seconds - VOICE_OFFSET_SECONDS,
      narration: scene.narration,
      sampleSeconds: sampleSeconds(key),
      saved,
      edited: edit?.edited ?? null,
      voiceOutdated: isVoiceOutdated(saved, edit),
    };
  });
};

const send = (res, status, type, body) => {
  res.writeHead(status, {
    "Content-Type": type,
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  res.end(body);
};

const sendJson = (res, status, value) =>
  send(res, status, "application/json; charset=utf-8", JSON.stringify(value));

const sendFile = (res, path, type) =>
  existsSync(path)
    ? send(res, 200, type, readFileSync(path))
    : sendJson(res, 404, { error: "見つからない" });

/** 音声を返す。Safari などの WebKit は部分取得（Range）に答えないと再生しない */
const sendAudio = (req, res, path) => {
  if (!existsSync(path)) return sendJson(res, 404, { error: "見つからない" });
  const data = readFileSync(path);
  const range = parseRange(req.headers.range, data.length);
  const headers = {
    "Content-Type": "audio/wav",
    "Accept-Ranges": "bytes",
    "Cache-Control": "no-store",
  };
  if (range === "invalid") {
    res.writeHead(416, {
      ...headers,
      "Content-Range": `bytes */${data.length}`,
    });
    return res.end();
  }
  if (range === null) {
    res.writeHead(200, { ...headers, "Content-Length": data.length });
    return res.end(data);
  }
  const part = data.subarray(range.start, range.end + 1);
  res.writeHead(206, {
    ...headers,
    "Content-Length": part.length,
    "Content-Range": `bytes ${range.start}-${range.end}/${data.length}`,
  });
  return res.end(part);
};

const readBody = (req) =>
  new Promise((ok, fail) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        fail(new Error("録音が大きすぎる"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => ok(Buffer.concat(chunks)));
    req.on("error", fail);
  });

/** 相談の文をこのパソコンのクリップボードへ（ブラウザによっては API が使えないため） */
const copyToClipboard = (text) =>
  new Promise((ok, fail) => {
    const child = spawn("pbcopy", [], {
      stdio: ["pipe", "ignore", "ignore"],
      env: { ...process.env, LC_CTYPE: "UTF-8" },
    });
    child.on("error", fail);
    child.on("close", (code) =>
      code === 0 ? ok() : fail(new Error(`pbcopy ${code}`)),
    );
    child.stdin.end(text);
  });

const handleJsonPost = async (req, res, url) => {
  const { text } = JSON.parse((await readBody(req)).toString("utf8"));
  if (typeof text !== "string") throw new Error("文がありません");
  if (url.pathname === "/api/clipboard") {
    if (text.length > MAX_CLIPBOARD_CHARS) throw new Error("文が長すぎます");
    await copyToClipboard(text);
    return sendJson(res, 200, { copied: true });
  }
  const m = /^\/api\/script\/([^/]+)$/.exec(url.pathname);
  const scene = m && scenesB.find((s) => voiceKeyOf(s.id) === m[1]);
  if (!scene) return sendJson(res, 404, { error: "見つからない" });
  saveScriptEdit(EDITS_FILE, m[1], scene.narration, text);
  return sendJson(res, 200, { scenes: sceneList() });
};

const handlePost = async (req, res, url) => {
  // application/json も別のサイトからは送れない（CORS の確認に答えないので届かない）
  if (req.headers["content-type"] === "application/json") {
    return handleJsonPost(req, res, url);
  }
  // audio/wav の指定は別のサイトからの送信を止める（CORS の確認に答えないので届かない）
  if (req.headers["content-type"] !== "audio/wav") {
    return sendJson(res, 415, { error: "audio/wav のみ" });
  }
  const m = /^\/api\/(takes|voices)\/([^/]+)$/.exec(url.pathname);
  if (!m || !isVoiceKey(m[2])) {
    return sendJson(res, 404, { error: "見つからない" });
  }
  const [, what, key] = m;
  const body = await readBody(req);
  if (what === "takes") {
    const kind = url.searchParams.get("kind") ?? "";
    const name = keepTake(join(ARCHIVE_DIR, "takes"), key, kind, body);
    return sendJson(res, 200, { name });
  }
  const file = saveVoice(VOICE_DIR, join(ARCHIVE_DIR, "old"), key, body);
  return sendJson(res, 200, { file, saved: savedVoice(VOICE_DIR, key) });
};

const handleGet = (req, res, url) => {
  const file = STATIC_FILES[url.pathname];
  if (file) return sendFile(res, join(HERE, file[0]), file[1]);
  if (url.pathname === "/api/scenes") {
    return sendJson(res, 200, { scenes: sceneList() });
  }
  const m = /^\/(sample|voice)\/([^/]+)$/.exec(url.pathname);
  if (m && isVoiceKey(m[2])) {
    const saved = m[1] === "voice" ? savedVoice(VOICE_DIR, m[2]) : null;
    const path =
      m[1] === "sample"
        ? samplePath(m[2])
        : saved && join(VOICE_DIR, saved.file);
    if (path) return sendAudio(req, res, path);
  }
  return sendJson(res, 404, { error: "見つからない" });
};

const isLocalHost = (host) =>
  [`localhost:${PORT}`, `127.0.0.1:${PORT}`, `[::1]:${PORT}`].includes(host);

const server = createServer(async (req, res) => {
  try {
    if (!isLocalHost(req.headers.host)) {
      return sendJson(res, 403, { error: "このパソコンからだけ使える" });
    }
    const url = new URL(req.url, `http://localhost:${PORT}`);
    if (req.method === "POST") return await handlePost(req, res, url);
    if (req.method === "GET") return handleGet(req, res, url);
    return sendJson(res, 405, { error: "使えない方法" });
  } catch (error) {
    return sendJson(res, 400, { error: String(error.message ?? error) });
  }
});

mkdirSync(VOICE_DIR, { recursive: true });
server.on("error", (error) => {
  console.error(
    error.code === "EADDRINUSE"
      ? `ポート ${PORT} は使用中です。前の録音アプリを Ctrl+C で止めてください。`
      : `起動できません: ${error.message}`,
  );
  process.exit(1);
});
server.listen(PORT, "localhost", () => {
  const url = `http://localhost:${PORT}/`;
  console.log(`録音アプリ: ${url}`);
  console.log(`保存先: ${VOICE_DIR}`);
  console.log("終えるときは Ctrl+C");
  if (!process.env.NO_OPEN) spawn("open", [url], { stdio: "ignore" });
});
