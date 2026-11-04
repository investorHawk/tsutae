"""案 B のナレーション音声を AivisSpeech Engine で場面ごとに作る（標準ライブラリだけ）。

使い方: cd video && python3 scripts/make_voice.py [--engine URL] [--speaker ID]

scripts/narration.json の各場面の read を読み上げ、
public/voice/b/<id>.wav と src/voice.generated.json（[{"id", "file", "seconds"}]）を書く。
エンジンに繋がらないときは日本語のエラーを出して終了コード 1 で終わる。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
NARRATION_FILE = ROOT / "scripts" / "narration.json"
VOICE_DIR = ROOT / "public" / "voice" / "b"
MANIFEST_FILE = ROOT / "src" / "voice.generated.json"

DEFAULT_ENGINE = "http://127.0.0.1:10101"
TIMEOUT_SECONDS = 120

# 読み上げの調整（少し速め・前後の無音は短め。場面の前後の間は動画側の lead / tail でとる）
QUERY_OVERRIDES: dict[str, float] = {
    "speedScale": 1.08,
    "prePhonemeLength": 0.05,
    "postPhonemeLength": 0.1,
}


class VoiceError(Exception):
    """利用者に見せる日本語のエラー"""


def load_narration(path: Path) -> dict[str, Any]:
    """台本を読み、形を確かめる"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise VoiceError(f"台本が見つからない: {path}") from e
    except json.JSONDecodeError as e:
        raise VoiceError(f"台本の JSON が壊れている: {path}: {e}") from e
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(scenes, list) or not scenes:
        raise VoiceError(f"台本に scenes が無い: {path}")
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise VoiceError(f"台本の {i} 番目の場面が object でない")
        for key in ("id", "read"):
            value = scene.get(key)
            if not isinstance(value, str) or not value.strip():
                raise VoiceError(f"台本の {i} 番目の場面に {key} が無い")
    return data


def _post(url: str, body: bytes | None = None) -> bytes:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    endpoint = url.split("?", 1)[0]  # エラー文に長いクエリを出さない
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise VoiceError(
            f"エンジンがエラーを返した（HTTP {e.code}）: {endpoint}\n{detail}"
        ) from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise VoiceError(
            f"AivisSpeech Engine に繋がらない: {endpoint}\n"
            f"（{e}）\nエンジンを起動してから、もう一度実行してください。"
        ) from e


def synthesize(engine: str, speaker: int, text: str) -> bytes:
    """audio_query → synthesis で WAV のバイト列を返す"""
    params = urllib.parse.urlencode({"text": text, "speaker": speaker})
    raw_query = _post(f"{engine}/audio_query?{params}")
    try:
        query = json.loads(raw_query)
    except json.JSONDecodeError as e:
        raise VoiceError(f"audio_query の応答が JSON でない: {e}") from e
    tuned = {**query, **QUERY_OVERRIDES}
    body = json.dumps(tuned, ensure_ascii=False).encode("utf-8")
    return _post(f"{engine}/synthesis?speaker={speaker}", body)


def wav_seconds(data: bytes) -> float:
    """WAV の長さ（フレーム数 / レート、小数 3 桁）"""
    try:
        with wave.open(BytesIO(data), "rb") as w:
            return round(w.getnframes() / w.getframerate(), 3)
    except (wave.Error, EOFError, ZeroDivisionError) as e:
        raise VoiceError(f"エンジンの応答が WAV として読めない: {e}") from e


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="案 B のナレーション音声を場面ごとに作る（AivisSpeech Engine）"
    )
    parser.add_argument(
        "--engine",
        default=DEFAULT_ENGINE,
        help=f"エンジンの URL（既定 {DEFAULT_ENGINE}）",
    )
    parser.add_argument(
        "--speaker",
        type=int,
        default=None,
        help="話者の style id（既定は narration.json の speaker）",
    )
    return parser.parse_args(argv)


def make_voice(engine: str, speaker: int, scenes: list[dict[str, Any]]) -> list[dict]:
    """場面ごとに WAV を書き、声の一覧（id・file・seconds）を返す"""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    clips: list[dict] = []
    for scene in scenes:
        scene_id = scene["id"]
        data = synthesize(engine, speaker, scene["read"])
        seconds = wav_seconds(data)
        (VOICE_DIR / f"{scene_id}.wav").write_bytes(data)
        clips.append(
            {"id": scene_id, "file": f"voice/b/{scene_id}.wav", "seconds": seconds}
        )
        print(f"  {scene_id:<16} {seconds:7.3f} 秒", flush=True)
    return clips


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    engine = args.engine.rstrip("/")
    try:
        narration = load_narration(NARRATION_FILE)
        speaker = args.speaker if args.speaker is not None else narration.get("speaker")
        if not isinstance(speaker, int):
            raise VoiceError(
                "話者が決まらない（--speaker か narration.json の speaker）"
            )
        print(f"make_voice: {engine} 話者 {speaker} / {len(narration['scenes'])} 場面")
        clips = make_voice(engine, speaker, narration["scenes"])
    except VoiceError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    text = json.dumps(clips, ensure_ascii=False, indent=2) + "\n"
    MANIFEST_FILE.write_text(text, encoding="utf-8")
    total = sum(c["seconds"] for c in clips)
    print(f"  {'合計':<14} {total:7.3f} 秒")
    print(f"make_voice: {VOICE_DIR} と {MANIFEST_FILE} を書いた")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
