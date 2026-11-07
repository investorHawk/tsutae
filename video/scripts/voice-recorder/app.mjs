// 録音アプリの画面。リハーサルも本番も同じ録り方で録り、結果の扱いだけが違う。
import { processTake } from "/audio.mjs";
import {
  consultPrompt,
  countChars,
  diffChars,
  normalizeScript,
} from "/script.mjs";

const COUNTDOWN_SECONDS = 3;
const SAMPLE_RATE = 48000;
const VOICE_PATH = "video/public/voice";
const KIND_LABEL = { rehearsal: "リハーサル", record: "本番" };
const LEVEL_LABEL = { ok: "問題なし", warn: "注意", ng: "問題あり" };

const main = document.getElementById("main");
const nav = document.getElementById("scenes");
const micSelect = document.getElementById("mic");

const state = {
  scenes: [],
  key: null,
  reviews: {}, // 場面ごとの最新の結果
  error: null,
  capture: null,
  opening: false, // マイクを開いている間（許可待ちを含む）
  stream: null, // 開いたままのマイク
  drafts: {}, // 場面ごとの編集中の原稿（ここにあれば編集中）
};

const h = (tag, props = {}, ...children) => {
  const el = document.createElement(tag);
  Object.assign(el, props);
  el.append(...children.filter((c) => c !== null && c !== undefined));
  return el;
};

const sec = (value) => `${value.toFixed(1)} 秒`;
const currentScene = () => state.scenes.find((s) => s.key === state.key);
const isCapturing = () => state.capture !== null;

const loadScenes = async () => {
  const res = await fetch("/api/scenes");
  state.scenes = (await res.json()).scenes;
};

const stopAudio = () =>
  document.querySelectorAll("audio").forEach((a) => a.pause());

// ---- 録音 ----

/**
 * 一度許可されたマイクは開いたままにする。ブラウザによっては開くたびに許可を求めるので、
 * 2 本目以降の録音で止まらないようにする。マイクを選び直したときだけ開き直す
 */
const getStream = async () => {
  const live = state.stream
    ?.getAudioTracks()
    .some((t) => t.readyState === "live");
  if (live) return state.stream;
  const deviceId = micSelect.value || undefined;
  state.stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      deviceId,
      channelCount: 1,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    },
  });
  return state.stream;
};

const releaseStream = () => {
  state.stream?.getTracks().forEach((t) => t.stop());
  state.stream = null;
};

const openMic = async () => {
  const stream = await getStream();
  const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
  await ctx.audioWorklet.addModule("/worklet.js");
  const node = new AudioWorkletNode(ctx, "capture");
  const mute = ctx.createGain();
  mute.gain.value = 0;
  ctx.createMediaStreamSource(stream).connect(node);
  node.connect(mute).connect(ctx.destination);
  await ctx.resume();
  return { ctx, node };
};

const closeMic = ({ ctx, node }) => {
  node.port.onmessage = null;
  ctx.close();
};

const concat = (blocks) => {
  const out = new Float32Array(blocks.reduce((n, b) => n + b.length, 0));
  let at = 0;
  for (const block of blocks) {
    out.set(block, at);
    at += block.length;
  }
  return out;
};

const loudness = (block) => {
  let peak = 0;
  for (const s of block) peak = Math.max(peak, Math.abs(s));
  return peak;
};

/** 声の大きさバーの幅（-60〜0 dBFS を 0〜100%）。普通の声でも振れるように dB で出す */
const meterPercent = (peak) => {
  const db = 20 * Math.log10(Math.max(peak, 1e-3));
  return Math.min(100, ((db + 60) / 60) * 100);
};

const startTake = async (kind) => {
  if (state.opening || state.capture) return;
  stopAudio();
  document.activeElement?.blur();
  state.error = null;
  state.opening = true;
  render();
  const scene = currentScene();
  try {
    const mic = await openMic();
    await refreshMicList();
    const capture = {
      kind,
      scene,
      mic,
      phase: "countdown",
      quiet: [],
      blocks: [],
      peak: 0,
      startedAt: 0,
      goTimer: 0,
      frame: 0,
    };
    state.capture = capture;
    state.opening = false;
    mic.node.port.onmessage = ({ data }) => onBlock(capture, data);
    render();
    runCountdown(capture, COUNTDOWN_SECONDS);
  } catch (error) {
    state.error = micErrorText(error);
    render();
  } finally {
    state.opening = false;
  }
};

const micErrorText = (error) =>
  error.name === "NotAllowedError"
    ? "マイクの使用が許可されていません。アドレスバーのマイクのアイコンから許可し、もう一度押してください。"
    : `マイクを開けません: ${error.message}`;

const onBlock = (capture, block) => {
  capture.peak = Math.max(capture.peak * 0.92, loudness(block));
  (capture.phase === "countdown" ? capture.quiet : capture.blocks).push(block);
};

const runCountdown = (capture, left) => {
  if (state.capture !== capture) return;
  const number = document.getElementById("countdown");
  if (left === 0) {
    capture.phase = "recording";
    capture.startedAt = performance.now();
    render();
    tickLive(capture);
    return;
  }
  if (number) number.textContent = String(left);
  capture.goTimer = setTimeout(() => runCountdown(capture, left - 1), 1000);
};

const tickLive = (capture) => {
  if (state.capture !== capture) return;
  const elapsed = (performance.now() - capture.startedAt) / 1000;
  const budget = capture.scene.budget;
  const over = elapsed > budget;
  const timer = document.getElementById("elapsed");
  timer.textContent = elapsed.toFixed(1);
  document.getElementById("timer").classList.toggle("over", over);
  const bar = document.getElementById("time-bar");
  bar.classList.toggle("over", over);
  bar.firstChild.style.width = `${Math.min(100, (elapsed / budget) * 100)}%`;
  const level = document.getElementById("level-bar");
  level.classList.toggle("hot", capture.peak >= 0.9);
  level.firstChild.style.width = `${meterPercent(capture.peak)}%`;
  capture.frame = requestAnimationFrame(() => tickLive(capture));
};

const cancelTake = () => {
  const capture = state.capture;
  if (!capture) return;
  clearTimeout(capture.goTimer);
  cancelAnimationFrame(capture.frame);
  closeMic(capture.mic);
  state.capture = null;
  render();
};

const stopTake = async () => {
  const capture = state.capture;
  if (!capture || capture.phase !== "recording") return;
  cancelAnimationFrame(capture.frame);
  closeMic(capture.mic);
  state.capture = null;
  const { kind, scene } = capture;
  const take = processTake(
    concat(capture.blocks),
    concat(capture.quiet),
    SAMPLE_RATE,
    scene.budget,
  );
  const review = {
    kind,
    take,
    url: URL.createObjectURL(new Blob([take.wav], { type: "audio/wav" })),
    savedFile: null,
    error: null,
  };
  const previous = state.reviews[scene.key];
  if (previous) URL.revokeObjectURL(previous.url);
  state.reviews[scene.key] = review;
  await keepCopy(scene.key, review);
  if (kind === "record" && take.checks.every((c) => c.level === "ok")) {
    await saveReview(scene.key, review);
  } else {
    render();
    showReview();
  }
};

// ---- 保存 ----

const postWav = async (path, wav) => {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "audio/wav" },
    body: wav,
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? `HTTP ${res.status}`);
  return body;
};

const keepCopy = async (key, review) => {
  try {
    await postWav(`/api/takes/${key}?kind=${review.kind}`, review.take.wav);
  } catch (error) {
    review.error = `控えを残せませんでした: ${error.message}`;
  }
};

const saveReview = async (key, review) => {
  try {
    const { file } = await postWav(`/api/voices/${key}`, review.take.wav);
    review.savedFile = file;
    review.error = null;
    await loadScenes();
  } catch (error) {
    review.error = `保存できませんでした: ${error.message}`;
  }
  render();
  showReview();
};

// ---- 描画 ----

const renderNav = () => {
  const saved = state.scenes.filter((s) => s.saved);
  const total = saved.reduce((n, s) => n + (s.saved.seconds ?? 0), 0);
  const budget = state.scenes.reduce((n, s) => n + s.budget, 0);
  const buttons = state.scenes.map((scene, i) => {
    const over = scene.saved && scene.saved.seconds > scene.budget;
    return h(
      "button",
      {
        className: scene.key === state.key ? "current" : "",
        disabled: isCapturing(),
        onclick: () => {
          state.key = scene.key;
          state.error = null;
          render();
        },
      },
      h("span", { textContent: `${i + 1}. ${scene.title}` }),
      h("span", {
        className: `mark ${over ? "over" : ""}`,
        textContent: `${scene.saved ? (over ? "△" : "✓") : ""}${scene.edited ? "✎" : ""}`,
      }),
      h("small", {
        textContent: scene.saved
          ? `保存済み ${sec(scene.saved.seconds ?? 0)} / 目標 ${sec(scene.budget)}`
          : `目標 ${sec(scene.budget)}`,
      }),
    );
  });
  const edits = state.scenes.filter((s) => s.edited).length;
  const finished = saved.length === state.scenes.length;
  const summary = h(
    "div",
    { id: "total" },
    h("div", {
      textContent: `保存 ${saved.length} / ${state.scenes.length} 本`,
    }),
    h("div", {
      textContent: `声の合計 ${sec(total)} / 使える時間 ${sec(budget)}`,
    }),
    edits > 0
      ? h("div", {
          textContent: `原稿の変更 ${edits} 場面（✎）`,
        })
      : null,
    finished
      ? h("div", {
          className: "mark",
          textContent:
            "全部そろいました。Claude に「録音が終わった」と伝えてください。",
        })
      : null,
  );
  nav.replaceChildren(...buttons, summary);
};

// ---- 原稿の変更 ----

const savedScript = (scene) => scene.edited ?? scene.narration;
const isEditing = (scene) => Object.hasOwn(state.drafts, scene.key);
const draftText = (scene) => normalizeScript(state.drafts[scene.key] ?? "");

const postJson = async (path, value) => {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error ?? `HTTP ${res.status}`);
  return body;
};

const diffNodes = (before, after) =>
  diffChars(before, after).map(({ type, text }) => {
    if (type === "del") return h("del", { textContent: text });
    if (type === "add") return h("ins", { textContent: text });
    return h("span", { textContent: text });
  });

/** 元の文からどう変わったか */
const changesNodes = (scene, text) => {
  if (text === scene.narration) {
    return [h("p", { className: "note", textContent: "元の文と同じです。" })];
  }
  const before = countChars(scene.narration);
  const after = countChars(text);
  const sign = after >= before ? "+" : "";
  return [
    h("p", {
      className: "note",
      textContent: `元の文からの変更（赤の取り消し線＝消した文字、緑＝足した文字）　字数 ${before} → ${after}（${sign}${after - before}）`,
    }),
    h("p", { className: "diff" }, ...diffNodes(scene.narration, text)),
  ];
};

const setNotice = (kind, text, promptText = null) => {
  const box = document.getElementById("script-notice");
  if (!box) return;
  box.replaceChildren(
    h("div", { className: kind, textContent: text }),
    ...(promptText === null
      ? []
      : [
          h("textarea", {
            className: "script-input",
            readOnly: true,
            rows: 5,
            value: promptText,
          }),
        ]),
  );
};

const consultClaude = async (scene, text) => {
  if (text === scene.narration) {
    setNotice("note", "元の文と同じなので、相談する変更がありません。");
    return;
  }
  const promptText = consultPrompt({
    index: state.scenes.indexOf(scene) + 1,
    title: scene.title,
    budget: scene.budget,
    original: scene.narration,
    edited: text,
  });
  try {
    await postJson("/api/clipboard", { text: promptText });
    setNotice(
      "done",
      "/btw 入りの相談の文をコピーしました。Claude Code の入力欄に貼り付けて送ってください。",
    );
  } catch (error) {
    setNotice(
      "error",
      `コピーできませんでした（${error.message}）。下の文を手でコピーしてください。`,
      promptText,
    );
  }
};

const saveScript = async (scene, text) => {
  try {
    const { scenes } = await postJson(`/api/script/${scene.key}`, { text });
    state.scenes = scenes;
    const { [scene.key]: _saved, ...others } = state.drafts;
    state.drafts = others;
    render();
    const updated = currentScene();
    setNotice(
      "done",
      updated.edited ? "変更後の原稿を保存しました。" : "元の文に戻しました。",
    );
  } catch (error) {
    setNotice("error", `保存できませんでした: ${error.message}`);
  }
};

const smallButton = (textContent, onclick, kind = "") =>
  h("button", { className: `btn small ${kind}`, textContent, onclick });

const editingBlock = (scene) => {
  const changes = h(
    "div",
    { id: "script-changes" },
    ...changesNodes(scene, draftText(scene)),
  );
  const input = h("textarea", {
    className: "script-input",
    id: "script-input",
    rows: 5,
    value: state.drafts[scene.key],
    oninput: (event) => {
      state.drafts[scene.key] = event.target.value;
      changes.replaceChildren(...changesNodes(scene, draftText(scene)));
    },
  });
  return [
    input,
    h(
      "div",
      { className: "actions tight" },
      smallButton(
        "変更を保存",
        () => saveScript(scene, state.drafts[scene.key]),
        "primary",
      ),
      smallButton("Claude に相談", () =>
        consultClaude(scene, draftText(scene)),
      ),
      smallButton("やめる", () => {
        const { [scene.key]: _dropped, ...others } = state.drafts;
        state.drafts = others;
        render();
      }),
    ),
    changes,
  ];
};

const viewingBlock = (scene) => {
  const script = savedScript(scene);
  return [
    h("p", { className: "script", textContent: script }),
    h(
      "div",
      { className: "actions tight" },
      smallButton("原稿を変更", () => {
        state.drafts = { ...state.drafts, [scene.key]: script };
        render();
        document.getElementById("script-input")?.focus();
      }),
      scene.edited
        ? smallButton("Claude に相談", () => consultClaude(scene, script))
        : null,
      scene.edited
        ? smallButton("元の文に戻す", () => saveScript(scene, scene.narration))
        : null,
    ),
    ...(scene.edited ? changesNodes(scene, script) : []),
    scene.voiceOutdated
      ? h("div", {
          className: "warn",
          textContent:
            "保存済みの声は変更前の文です。この原稿で録り直してください。",
        })
      : null,
    scene.edited && scene.sampleSeconds !== null
      ? h("p", {
          className: "note",
          textContent: "合成音声は元の文のままです。",
        })
      : null,
  ].filter(Boolean);
};

const scriptBlock = (scene) => {
  if (isCapturing()) {
    const text = isEditing(scene) ? draftText(scene) : savedScript(scene);
    return [h("p", { className: "script", textContent: text })];
  }
  return [
    ...(isEditing(scene) ? editingBlock(scene) : viewingBlock(scene)),
    h("div", { id: "script-notice" }),
  ];
};

const sceneHeader = (scene) => {
  const index = state.scenes.indexOf(scene) + 1;
  const sample =
    scene.sampleSeconds === null || isCapturing()
      ? null
      : h(
          "span",
          {},
          `合成音声（${sec(scene.sampleSeconds)}）`,
          h("audio", {
            controls: true,
            preload: "none",
            src: `/sample/${scene.key}`,
          }),
        );
  return [
    h("p", {
      className: "eyebrow",
      textContent: `場面 ${index} / ${state.scenes.length}`,
    }),
    h("h2", { textContent: scene.title }),
    h(
      "div",
      { className: "goal" },
      h("strong", { textContent: `${sec(scene.budget)} 以内` }),
      h("span", { textContent: `この場面は ${scene.seconds} 秒` }),
      sample,
    ),
    ...scriptBlock(scene),
  ];
};

const savedRow = (scene) =>
  scene.saved
    ? h(
        "div",
        { className: "saved-row" },
        h("span", {
          className: "mark",
          textContent: `保存済み ${sec(scene.saved.seconds ?? 0)}`,
        }),
        h("audio", {
          controls: true,
          preload: "none",
          src: `/voice/${scene.key}?t=${Date.now()}`,
        }),
      )
    : null;

const idleActions = (scene) => {
  return [
    h(
      "div",
      { className: "actions" },
      h("button", {
        className: "btn primary",
        textContent: "リハーサル",
        onclick: () => startTake("rehearsal"),
      }),
      h("button", {
        className: "btn rec",
        textContent: "本番を録音",
        onclick: () => startTake("record"),
      }),
    ),
    h("p", {
      className: "note",
      textContent:
        "リハーサルも録音しています。うまく言えたら、そのまま本番として保存できます。",
    }),
    savedRow(scene),
  ];
};

const captureView = (capture) => {
  const kindClass = capture.kind === "rehearsal" ? "rehearsal" : "";
  const cancel = h("button", {
    className: "btn",
    textContent: "やめる",
    onclick: cancelTake,
  });
  if (capture.phase === "countdown") {
    return h(
      "div",
      { className: `live ${kindClass}` },
      h("p", {
        className: "live-label",
        textContent: `${KIND_LABEL[capture.kind]}: 数字が消えたら話し始める。静かに待つ`,
      }),
      h("div", {
        className: "countdown",
        id: "countdown",
        textContent: String(COUNTDOWN_SECONDS),
      }),
      h("div", { className: "actions" }, cancel),
    );
  }
  const label =
    capture.kind === "rehearsal"
      ? "リハーサル中（これも録音しています）"
      : "本番 録音中";
  return h(
    "div",
    { className: `live ${kindClass}` },
    h("p", { className: "live-label", textContent: label }),
    h(
      "div",
      { className: "timer", id: "timer" },
      h("span", { id: "elapsed", textContent: "0.0" }),
      h("small", { textContent: ` / ${sec(capture.scene.budget)}` }),
    ),
    h("div", { className: "bar", id: "time-bar" }, h("i")),
    h("div", { className: "bar-label", textContent: "声の大きさ" }),
    h("div", { className: "bar level", id: "level-bar" }, h("i")),
    h(
      "div",
      { className: "actions" },
      h("button", {
        className: "btn rec",
        textContent: "止める（スペースキー）",
        onclick: stopTake,
      }),
      cancel,
    ),
  );
};

const reviewStats = (scene, take) => {
  const seconds = take.metrics.seconds;
  const diff = scene.budget - seconds;
  const stat = (value, label) =>
    h(
      "div",
      {},
      h("b", { textContent: value }),
      h("span", { textContent: label }),
    );
  return h(
    "div",
    { className: "stats" },
    stat(sec(seconds), "話した長さ"),
    stat(sec(scene.budget), "目標"),
    stat(diff >= 0 ? `残り ${sec(diff)}` : `超過 ${sec(-diff)}`, "目標との差"),
    scene.sampleSeconds === null
      ? null
      : stat(sec(scene.sampleSeconds), "合成音声"),
  );
};

const nextSceneButton = (scene) => {
  const index = state.scenes.indexOf(scene);
  const next = state.scenes[index + 1];
  return next
    ? h("button", {
        className: "btn primary",
        textContent: `次の場面へ（${next.title}）`,
        onclick: () => {
          state.key = next.key;
          render();
        },
      })
    : null;
};

const reviewActions = (scene, review) => {
  const levels = review.take.checks.map((c) => c.level);
  const worst = levels.includes("ng")
    ? "ng"
    : levels.includes("warn")
      ? "warn"
      : "ok";
  const saveLabel = {
    ok: "この音声を本番として保存",
    warn: "注意を確かめたうえで保存",
    ng: "問題があるが、それでも保存",
  }[worst];
  const retry = [
    h("button", {
      className: "btn",
      textContent: "もう一度リハーサル",
      onclick: () => startTake("rehearsal"),
    }),
    h("button", {
      className: "btn rec",
      textContent: "本番を録音",
      onclick: () => startTake("record"),
    }),
  ];
  if (review.savedFile) {
    return h("div", { className: "actions" }, nextSceneButton(scene), ...retry);
  }
  return h(
    "div",
    { className: "actions" },
    h("button", {
      className: worst === "ok" ? "btn primary" : "btn",
      textContent: saveLabel,
      onclick: () => saveReview(scene.key, review),
    }),
    ...retry,
  );
};

const reviewView = (scene, review) => {
  const { take, kind, savedFile, error } = review;
  return h(
    "section",
    { className: "review" },
    h("h3", { textContent: `${KIND_LABEL[kind]}の結果` }),
    reviewStats(scene, take),
    h("audio", { controls: true, src: review.url }),
    h("p", {
      className: "note",
      textContent:
        "読み間違いは自動では分かりません。聞いて確かめてください（前後の無音を切り、音量をそろえた後の音です）。",
    }),
    h(
      "ul",
      { className: "checks" },
      ...take.checks.map((check) =>
        h(
          "li",
          {},
          h("span", {
            className: `tag ${check.level}`,
            textContent: LEVEL_LABEL[check.level],
          }),
          h("span", { textContent: check.label }),
        ),
      ),
    ),
    savedFile
      ? h("div", {
          className: "done",
          textContent: `${VOICE_PATH}/${savedFile} に保存しました。前の録音があれば video/out/voice/old/ に移しました。`,
        })
      : null,
    error ? h("div", { className: "error", textContent: error }) : null,
    reviewActions(scene, review),
    savedFile ? null : savedRow(scene),
  );
};

const renderMain = () => {
  const scene = currentScene();
  if (!scene) return;
  const review = state.reviews[scene.key];
  const lower = state.capture
    ? [captureView(state.capture)]
    : review
      ? [reviewView(scene, review)]
      : idleActions(scene);
  const error = state.error
    ? h("div", { className: "error", textContent: state.error })
    : state.opening
      ? h("div", {
          className: "done",
          textContent:
            "マイクの準備をしています。許可を求められたら「許可」を押してください。",
        })
      : null;
  main.replaceChildren(
    ...sceneHeader(scene),
    error ?? "",
    ...lower.filter(Boolean),
  );
};

const render = () => {
  document.body.classList.toggle("capturing", isCapturing());
  renderNav();
  renderMain();
};

/** 結果の欄を見える位置へ（幅の狭い画面では原稿の下に隠れるので） */
const showReview = () =>
  document.querySelector(".review")?.scrollIntoView({ block: "start" });

// ---- マイクの一覧とキー操作 ----

const refreshMicList = async () => {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const inputs = devices.filter((d) => d.kind === "audioinput" && d.label);
  if (inputs.length === 0) return;
  const selected = micSelect.value;
  micSelect.replaceChildren(
    ...inputs.map((d) =>
      h("option", { value: d.deviceId, textContent: d.label }),
    ),
  );
  if (inputs.some((d) => d.deviceId === selected)) micSelect.value = selected;
};

micSelect.addEventListener("change", releaseStream);

document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || !isCapturing()) return;
  event.preventDefault();
  stopTake();
});

const init = async () => {
  await loadScenes();
  state.key = (state.scenes.find((s) => !s.saved) ?? state.scenes[0]).key;
  await refreshMicList();
  render();
};

init().catch((error) => {
  main.textContent = `読み込めません: ${error.message}`;
});
