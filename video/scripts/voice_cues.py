"""先生の声を文字起こしし、字幕の塊の開始時刻を src/storyboards/bVoiceCues.ts に書く。

声はこのパソコンの中だけで処理する（Whisper。外へ送らない）。原稿と違う読み方は差として出す。
使い方（録り直したら実行する）: cd video && <whisper の入った python> scripts/voice_cues.py
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import unicodedata
import wave
from pathlib import Path

import whisper

ROOT = Path(__file__).resolve().parent.parent
VOICE_DIR = ROOT / "public" / "voice"
OUT_FILE = ROOT / "src" / "storyboards" / "bVoiceCues.ts"
DUMP = (
    'import { scenesB } from "./src/storyboards/b.ts";'
    'import { buildSubtitleChunks } from "./src/lib/subtitle.ts";'
    "console.log(JSON.stringify(scenesB.map((s) => ({"
    "key: s.id.split('-')[0], narration: s.narration,"
    "chunks: buildSubtitleChunks(s.narration).map((c) => c.lines.join(''))}))));"
)
IGNORED = re.compile(r"[\s、。，．「」『』・,.!?！？]")


def normalize(text: str) -> str:
    return IGNORED.sub("", unicodedata.normalize("NFKC", text))


def load_scenes() -> list[dict]:
    out = subprocess.check_output(
        ["node", "--import", "tsx", "--input-type=module", "-e", DUMP],
        cwd=ROOT,
        text=True,
    )
    return json.loads(out)


def char_times(result: dict) -> tuple[str, list[float]]:
    """文字起こしを 1 文字ずつに広げ、文字ごとの時刻を付ける。"""
    chars: list[str] = []
    times: list[float] = []
    for segment in result["segments"]:
        for word in segment["words"]:
            text = normalize(word["word"])
            span = word["end"] - word["start"]
            for i, c in enumerate(text):
                chars.append(c)
                times.append(word["start"] + span * i / max(1, len(text)))
    return "".join(chars), times


def chunk_starts(scene: dict, heard: str, times: list[float]) -> list[float]:
    """原稿の塊の頭に対応する、声の中の時刻。"""
    script = normalize(scene["narration"])
    matcher = difflib.SequenceMatcher(None, script, heard, autojunk=False)
    mapping = {
        block.a + i: block.b + i
        for block in matcher.get_matching_blocks()
        for i in range(block.size)
    }
    for op, a, b, c, d in matcher.get_opcodes():
        if op != "equal":
            print(f"  {scene['key']} 差: 原稿「{script[a:b]}」/ 声「{heard[c:d]}」")
    starts: list[float] = []
    at = 0
    for chunk in scene["chunks"]:
        i = at
        while i not in mapping and i < len(script):
            i += 1
        starts.append(round(times[mapping[i]], 2))
        at += len(normalize(chunk))
    return [0.0, *starts[1:]]


def file_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return round(w.getnframes() / w.getframerate(), 2)


def render(cues: dict[str, dict]) -> str:
    rows = "\n".join(
        f"  {key}: {{ seconds: {c['seconds']}, starts: {json.dumps(c['starts'])} }},"
        for key, c in cues.items()
    )
    return (
        "// 生成物: scripts/voice_cues.py が先生の声から書く。手で編集しない。\n"
        "/** seconds: 声のファイルの長さ。starts: 字幕の塊ごとの開始（声の頭から・秒） */\n"
        "export const VOICE_CUES: Record<\n"
        "  string,\n"
        "  { seconds: number; starts: readonly number[] }\n"
        "> = {\n"
        f"{rows}\n}};\n"
    )


def main() -> None:
    model = whisper.load_model("large-v3-turbo")
    cues = {}
    for scene in load_scenes():
        path = VOICE_DIR / f"{scene['key']}.wav"
        result = model.transcribe(
            str(path),
            language="ja",
            fp16=False,
            word_timestamps=True,
            initial_prompt=scene["narration"],
            condition_on_previous_text=False,
            temperature=0,
            verbose=None,
        )
        heard, times = char_times(result)
        print(f"{scene['key']}: {result['text'].strip()}")
        cues[scene["key"]] = {
            "seconds": file_seconds(path),
            "starts": chunk_starts(scene, heard, times),
        }
    OUT_FILE.write_text(render(cues), encoding="utf-8")


if __name__ == "__main__":
    main()
