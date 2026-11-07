"""案 B（DemoB）の BGM を合成して public/audio/bgm.wav に書く（標準ライブラリだけ）。

使い方: cd video && python3 scripts/make_bgm.py [--seconds N] [--seed S] [--out PATH]

- 既定は 175 秒（DemoB の長さと同じ。Remotion 側で尺に合わせて切り、フェードアウトする）。
- 曲はこのファイルの中で正弦波から合成する自作の音だけで、第三者の音源・サンプルは使わない。
  （著作権の制約が無い自作曲）
- 曲想: 診察室の話に合う、落ち着いて温かく前向きな器楽。F メジャー、88 BPM、
  F – C – Dm – B♭ の 4 和音の循環。パッド（左右で少しずらした正弦波）・ベル風のアルペジオ・
  柔らかいベース・ごく小さいシェイカー。8 小節ごとにアルペジオの音型やオクターブを変える。
- 速さの工夫: 1 小節分の音（和音 × 変化の種類ごと）を 1 度だけ合成して使い回す。
- 終わりに長さ・ピーク・RMS・かかった秒を表示する。
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
import wave
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from operator import add, mul
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "public" / "audio" / "bgm.wav"

SR = 44100
BPM = 88
BEATS_PER_BAR = 4
BARS_PER_SECTION = 8
TAIL_SAMPLES = round(2.0 * SR)  # パッドの余韻・エコーが次の小節に重なる長さ
FADE_IN_SECONDS = 2.0
FADE_OUT_SECONDS = 2.0  # ファイルの終わり（Remotion 側でも別にフェードアウトする）
PEAK_DBFS = -3.0
DEFAULT_SECONDS = 175.0
DEFAULT_SEED = 7
MAX_SECONDS = 600.0

# 各楽器の音量（正規化の前の相対値）
PAD_LEVEL = 0.10
BASS_LEVEL = 0.30
ARP_LEVEL = 0.16
SHAKER_LEVEL = 0.012


@dataclass(frozen=True)
class Chord:
    name: str
    bass: int  # MIDI 番号
    pad: tuple[int, ...]
    arp: tuple[int, ...]  # 低い順に 4 音


@dataclass(frozen=True)
class Variant:
    name: str
    pattern: tuple[int | None, ...]  # 8 分音符ごとの arp の番号（None は休み）
    octave: int  # arp の移調（半音）
    shaker: bool
    arp_gain: float
    ping: float  # ベルの倍音の強さ（高い音域では弱めて 2〜4kHz を強くしない）


# F メジャー: F – C – Dm – B♭（I – V – vi – IV）。パッドは近い音で動く配置
PROGRESSION: tuple[Chord, ...] = (
    Chord("F", 41, (57, 60, 65), (65, 69, 72, 77)),
    Chord("C", 36, (55, 60, 64), (64, 67, 72, 76)),
    Chord("Dm", 38, (57, 62, 65), (62, 65, 69, 74)),
    Chord("Bb", 34, (58, 62, 65), (62, 65, 70, 74)),
)

VARIANTS: tuple[Variant, ...] = (
    Variant("intro", (0, None, 1, None, 2, None, 3, None), 0, False, 0.8, 1.0),
    Variant("up", (0, 1, 2, 3, 1, 2, 3, 2), 0, False, 1.0, 1.0),
    Variant("wave", (0, 2, 1, 3, 2, 1, 3, 1), 0, True, 0.95, 0.9),
    Variant("high", (3, 2, 1, 0, 1, 2, 3, 2), 12, True, 0.6, 0.35),
)


class BgmError(Exception):
    """利用者に見せる日本語のエラー"""


def midi_to_freq(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def bar_samples(bpm: float) -> int:
    return round(SR * 60 * BEATS_PER_BAR / bpm)


def section_plan(sections: int, seed: int) -> list[int]:
    """8 小節ごとの変化の番号。最初は intro、あとは隣と同じにならないよう選ぶ"""
    rng = random.Random(seed)
    plan = [0]
    for _ in range(1, sections):
        choices = [i for i in range(1, len(VARIANTS)) if i != plan[-1]]
        plan.append(rng.choice(choices))
    return plan[:sections]


def _tone(freq: float, n: int, partials: Sequence[tuple[int, float]]) -> list[float]:
    """倍音つきの正弦波（partials は (倍数, 振幅)）"""
    sin = math.sin
    w = 2 * math.pi * freq / SR
    if len(partials) == 1:
        k, a = partials[0]
        return [a * sin(k * w * i) for i in range(n)]
    (k1, a1), (k2, a2) = partials[0], partials[1]
    rest = partials[2:]
    out = [a1 * sin(k1 * w * i) + a2 * sin(k2 * w * i) for i in range(n)]
    for k, a in rest:
        out = list(map(add, out, [a * sin(k * w * i) for i in range(n)]))
    return out


def _mix_into(
    dst: list[float], src: Sequence[float], at: int, gain: float
) -> list[float]:
    """dst の at から src * gain を足した新しい配列（dst より長い分は捨てる）"""
    end = min(len(dst), at + len(src))
    if end <= at:
        return list(dst)
    seg = [gain * x for x in src[: end - at]]
    return dst[:at] + list(map(add, dst[at:end], seg)) + dst[end:]


def _pad_envelope(n_bar: int) -> list[float]:
    """ゆっくり立ち上がり、小節の後ろの余韻で 0 に戻る（立ち上がり・余韻は余弦）"""
    attack = round(0.8 * SR)
    total = n_bar + TAIL_SAMPLES
    env = []
    for i in range(total):
        if i < attack:
            env.append(0.5 - 0.5 * math.cos(math.pi * i / attack))
        elif i < n_bar:
            env.append(1.0)
        else:
            t = (i - n_bar) / TAIL_SAMPLES
            env.append(0.5 + 0.5 * math.cos(math.pi * t))
    return env


def _render_pad(chord: Chord, n_bar: int) -> tuple[list[float], list[float]]:
    total = n_bar + TAIL_SAMPLES
    env = _pad_envelope(n_bar)
    left, right = [0.0] * total, [0.0] * total
    partials = ((1, 1.0), (2, 0.12), (3, 0.04))
    for note in chord.pad:
        for dst, cents in (("L", -5.0), ("R", 5.0)):
            wave_ = _tone(midi_to_freq(note + cents / 100), total, partials)
            shaped = list(map(mul, wave_, env))
            if dst == "L":
                left = _mix_into(left, shaped, 0, PAD_LEVEL)
            else:
                right = _mix_into(right, shaped, 0, PAD_LEVEL)
    return left, right


def _note_envelope(n: int, attack_s: float, tau_s: float) -> list[float]:
    """短い立ち上がり＋指数減衰。最後の 30ms で 0 に落とす（クリック防止）"""
    attack = max(1, round(attack_s * SR))
    release = round(0.03 * SR)
    k = 1.0 / (tau_s * SR)
    env = []
    for i in range(n):
        a = i / attack if i < attack else 1.0
        r = (n - 1 - i) / release if i > n - 1 - release else 1.0
        env.append(a * r * math.exp(-k * i))
    return env


def _bell(
    freq: float, n: int, env_body: list[float], env_ping: list[float], ping: float
) -> list[float]:
    """ベル／エレピ風: 基音はゆっくり、倍音は速く減衰"""
    body = _tone(freq, n, ((1, 1.0),))
    ping = _tone(freq, n, ((2, 0.28 * ping), (3, 0.06 * ping)))
    return list(map(add, map(mul, body, env_body), map(mul, ping, env_ping)))


def _render_arp(
    chord: Chord, variant: Variant, n_bar: int, rng: random.Random
) -> tuple[list[float], list[float]]:
    total = n_bar + TAIL_SAMPLES
    step = n_bar // len(variant.pattern)
    note_len = round(1.3 * SR)
    env_body = _note_envelope(note_len, 0.004, 0.45)
    env_ping = _note_envelope(note_len, 0.004, 0.12)
    left, right = [0.0] * total, [0.0] * total
    for k, idx in enumerate(variant.pattern):
        if idx is None:
            continue
        freq = midi_to_freq(chord.arp[idx] + variant.octave)
        tone = _bell(freq, note_len, env_body, env_ping, variant.ping)
        accent = 1.0 if k % 4 == 0 else 0.8
        vel = ARP_LEVEL * variant.arp_gain * accent * rng.uniform(0.9, 1.05)
        pan = 0.5 + (0.18 if k % 2 else -0.18)  # 0 = 左、1 = 右
        at = k * step
        left = _mix_into(left, tone, at, vel * math.cos(pan * math.pi / 2))
        right = _mix_into(right, tone, at, vel * math.sin(pan * math.pi / 2))
    delay = round(0.75 * SR * 60 / BPM)  # 付点 8 分のエコー（左右を入れ替えて返す）
    return _echo(left, right, delay, feedback=0.3, wet=0.28)


def _echo(
    left: list[float], right: list[float], delay: int, feedback: float, wet: float
) -> tuple[list[float], list[float]]:
    """ピンポン・エコー（新しい配列を返す）"""
    n = len(left)
    el, er = [0.0] * n, [0.0] * n
    for i in range(delay, n):
        j = i - delay
        el[i] = right[j] + feedback * er[j]
        er[i] = left[j] + feedback * el[j]
    fade = _tail_fade(n, round(0.3 * SR))
    # zip(strict=) は 3.10 から（python3 は 3.9 もありうる）ので map で同じ長さを足す
    out_l = list(map(lambda a, b, f: (a + wet * b) * f, left, el, fade))
    out_r = list(map(lambda a, b, f: (a + wet * b) * f, right, er, fade))
    return out_l, out_r


def _tail_fade(n: int, length: int) -> list[float]:
    """最後の length サンプルで 1 → 0（ブロックの終わりを無音にする）"""
    start = n - length
    return [1.0 if i < start else (n - 1 - i) / max(1, length - 1) for i in range(n)]


def _render_bass(chord: Chord, n_bar: int) -> list[float]:
    """ルートを 2 分音符で 2 回。柔らかい立ち上がり"""
    total = n_bar + TAIL_SAMPLES
    out = [0.0] * total
    half = n_bar // 2
    note_len = half + round(0.12 * SR)
    env = _note_envelope(note_len, 0.02, 1.6)
    tone = _tone(midi_to_freq(chord.bass), note_len, ((1, 1.0), (2, 0.25), (3, 0.06)))
    shaped = list(map(mul, tone, env))
    out = _mix_into(out, shaped, 0, BASS_LEVEL)
    return _mix_into(out, shaped, half, BASS_LEVEL * 0.85)


def _render_shaker(n_bar: int, rng: random.Random) -> list[float]:
    """16 分のごく小さいノイズ（2 点平均で角をとる）"""
    total = n_bar + TAIL_SAMPLES
    out = [0.0] * total
    step = n_bar // 16
    hit_len = round(0.045 * SR)
    env = _note_envelope(hit_len, 0.003, 0.012)
    for k in range(16):
        noise = [rng.uniform(-1, 1) for _ in range(hit_len + 1)]
        soft = [(noise[i] + noise[i + 1]) * 0.5 * env[i] for i in range(hit_len)]
        accent = (1.0, 0.45, 0.7, 0.45)[k % 4]
        out = _mix_into(out, soft, k * step, SHAKER_LEVEL * accent)
    return out


def render_block(chord: Chord, variant: Variant, seed: int) -> tuple[array, array]:
    """1 小節分（＋余韻 TAIL_SAMPLES）の左右。最初と最後は無音"""
    rng = random.Random(f"{seed}-{chord.name}-{variant.name}")
    n_bar = bar_samples(BPM)
    pad_l, pad_r = _render_pad(chord, n_bar)
    arp_l, arp_r = _render_arp(chord, variant, n_bar, rng)
    bass = _render_bass(chord, n_bar)
    left = list(map(add, map(add, pad_l, arp_l), bass))
    right = list(map(add, map(add, pad_r, arp_r), bass))
    if variant.shaker:
        shaker = _render_shaker(n_bar, rng)
        left = list(map(add, left, shaker))
        right = list(map(add, right, shaker))
    return array("d", left), array("d", right)


def apply_fades(channel: array, fade_in: int, fade_out: int) -> array:
    """頭 fade_in・尻 fade_out サンプルの直線フェード（新しい配列を返す）"""
    out = array("d", channel)
    n = len(out)
    for i in range(min(fade_in, n)):
        out[i] *= i / fade_in
    for i in range(max(0, n - fade_out), n):
        out[i] *= (n - 1 - i) / fade_out
    return out


def build_song(seconds: float, seed: int) -> tuple[array, array]:
    """小節のブロックを並べて重ね、頭と尻をフェードする"""
    n_bar = bar_samples(BPM)
    total = round(seconds * SR)
    bars = math.ceil(total / n_bar)
    plan = section_plan(math.ceil(bars / BARS_PER_SECTION), seed)
    cache: dict[tuple[int, int], tuple[array, array]] = {}
    left = array("d", bytes(8 * (bars * n_bar + TAIL_SAMPLES)))
    right = array("d", left)
    for b in range(bars):
        key = (b % len(PROGRESSION), plan[b // BARS_PER_SECTION])
        if key not in cache:
            cache[key] = render_block(PROGRESSION[key[0]], VARIANTS[key[1]], seed)
        bl, br = cache[key]
        at, end = b * n_bar, b * n_bar + len(bl)
        left[at:end] = array("d", map(add, left[at:end], bl))
        right[at:end] = array("d", map(add, right[at:end], br))
    fi, fo = round(FADE_IN_SECONDS * SR), round(FADE_OUT_SECONDS * SR)
    return (
        apply_fades(left[:total], fi, fo),
        apply_fades(right[:total], fi, fo),
    )


def normalize(channels: tuple[array, array], peak_dbfs: float) -> tuple[array, array]:
    """ピークを peak_dbfs に合わせる（新しい配列を返す）"""
    peak = max(max(max(c), -min(c)) for c in channels)
    if peak <= 0:
        raise BgmError("音が無い（ピークが 0）")
    gain = 10 ** (peak_dbfs / 20) / peak
    left, right = channels
    return array("d", (x * gain for x in left)), array("d", (x * gain for x in right))


def to_pcm16(left: array, right: array) -> array:
    """左右を交互に並べた 16bit PCM（リトルエンディアン）"""
    out = array("h", bytes(4 * len(left)))
    out[0::2] = array("h", (round(x * 32767) for x in left))
    out[1::2] = array("h", (round(x * 32767) for x in right))
    if sys.byteorder == "big":
        out.byteswap()
    return out


def write_wav(path: Path, pcm: array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _dbfs(x: float) -> float:
    return 20 * math.log10(x) if x > 0 else float("-inf")


def describe(pcm: array, elapsed: float) -> str:
    samples = array("h", pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    peak = max(max(samples), -min(samples)) / 32767
    rms = math.sqrt(sum(map(mul, samples, samples)) / len(samples)) / 32767
    seconds = len(samples) / 2 / SR
    return (
        f"長さ {seconds:.2f} 秒 / ピーク {_dbfs(peak):.2f} dBFS / "
        f"RMS {_dbfs(rms):.2f} dBFS / 生成 {elapsed:.1f} 秒"
    )


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="案 B（DemoB）の BGM を合成する")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if not (0 < args.seconds <= MAX_SECONDS):
        raise BgmError(
            f"--seconds は 0 より大きく {MAX_SECONDS:g} 以下: {args.seconds}"
        )
    return args


def main(argv: Sequence[str] | None = None) -> int:
    started = time.perf_counter()
    try:
        args = parse_args(argv)
        song = normalize(build_song(args.seconds, args.seed), PEAK_DBFS)
        pcm = to_pcm16(*song)
        write_wav(args.out, pcm)
    except (BgmError, OSError) as e:
        print(f"make_bgm: {e}", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started
    print(f"make_bgm: {args.out}")
    print(f"make_bgm: {describe(pcm, elapsed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
