"""make_bgm.py の単体テスト（標準ライブラリの unittest だけ）。

使い方: cd video && python3 -m unittest scripts/test_make_bgm.py
"""

from __future__ import annotations

import io
import math
import sys
import tempfile
import unittest
import wave
from array import array
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_bgm as bgm  # noqa: E402


def peak_of(*channels: array) -> float:
    return max(max(max(c), -min(c)) for c in channels)


class TestBasics(unittest.TestCase):
    def test_midi_to_freq(self) -> None:
        self.assertAlmostEqual(bgm.midi_to_freq(69), 440.0)
        self.assertAlmostEqual(bgm.midi_to_freq(57), 220.0)

    def test_tempo_in_range(self) -> None:
        self.assertGreaterEqual(bgm.BPM, 84)
        self.assertLessEqual(bgm.BPM, 92)

    def test_bar_samples(self) -> None:
        self.assertEqual(bgm.bar_samples(88), round(bgm.SR * 240 / 88))

    def test_progression_has_four_chords(self) -> None:
        self.assertEqual(len(bgm.PROGRESSION), 4)
        for chord in bgm.PROGRESSION:
            self.assertEqual(len(chord.arp), 4)

    def test_arp_stays_below_presence_band(self) -> None:
        # ベルの基音は 2kHz 未満（2〜4kHz を強くしない）
        top = max(
            bgm.midi_to_freq(n + v.octave)
            for c in bgm.PROGRESSION
            for n in c.arp
            for v in bgm.VARIANTS
        )
        self.assertLess(top, 2000)


class TestSectionPlan(unittest.TestCase):
    def test_first_is_intro_and_no_repeat(self) -> None:
        plan = bgm.section_plan(9, seed=3)
        self.assertEqual(len(plan), 9)
        self.assertEqual(plan[0], 0)
        for i in range(1, len(plan)):
            self.assertNotEqual(plan[i - 1], plan[i])
        for v in plan:
            self.assertIn(v, range(len(bgm.VARIANTS)))

    def test_deterministic(self) -> None:
        self.assertEqual(bgm.section_plan(7, seed=5), bgm.section_plan(7, seed=5))

    def test_seed_changes_plan(self) -> None:
        plans = {tuple(bgm.section_plan(8, seed=s)) for s in range(6)}
        self.assertGreater(len(plans), 1)


class TestBlock(unittest.TestCase):
    def test_block_length_and_silent_edges(self) -> None:
        n = bgm.bar_samples(bgm.BPM)
        left, right = bgm.render_block(bgm.PROGRESSION[0], bgm.VARIANTS[1], seed=1)
        self.assertEqual(len(left), n + bgm.TAIL_SAMPLES)
        self.assertEqual(len(right), len(left))
        for ch in (left, right):
            self.assertLess(abs(ch[0]), 1e-3)
            self.assertLess(abs(ch[-1]), 1e-3)
            self.assertGreater(peak_of(ch), 0.01)


class TestSong(unittest.TestCase):
    def test_build_song_length_and_fade_in(self) -> None:
        left, right = bgm.build_song(6.0, seed=2)
        self.assertEqual(len(left), round(6.0 * bgm.SR))
        self.assertEqual(len(right), len(left))
        self.assertEqual(left[0], 0.0)
        self.assertEqual(right[0], 0.0)
        # 冒頭 2 秒のフェードインの途中は、その後より小さい
        early = peak_of(left[: bgm.SR // 4])
        later = peak_of(left[3 * bgm.SR : 4 * bgm.SR])
        self.assertLess(early, later)

    def test_normalize_peak_and_no_mutation(self) -> None:
        left = array("d", [0.0, 0.5, -2.0, 1.0])
        right = array("d", [0.1, -0.2, 0.3, 0.0])
        before = (list(left), list(right))
        nl, nr = bgm.normalize((left, right), peak_dbfs=-3.0)
        self.assertEqual((list(left), list(right)), before)
        self.assertAlmostEqual(peak_of(nl, nr), 10 ** (-3 / 20))

    def test_fade_does_not_mutate(self) -> None:
        ch = array("d", [1.0] * 100)
        out = bgm.apply_fades(ch, fade_in=10, fade_out=10)
        self.assertEqual(list(ch), [1.0] * 100)
        self.assertEqual(out[0], 0.0)
        self.assertEqual(out[-1], 0.0)
        self.assertEqual(out[50], 1.0)


class TestMain(unittest.TestCase):
    def test_writes_wav(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "sub" / "bgm.wav"
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = bgm.main(["--seconds", "5", "--seed", "1", "--out", str(out)])
            self.assertEqual(code, 0)
            with wave.open(str(out), "rb") as w:
                self.assertEqual(w.getframerate(), 44100)
                self.assertEqual(w.getsampwidth(), 2)
                self.assertEqual(w.getnchannels(), 2)
                self.assertEqual(w.getnframes(), 5 * 44100)
                data = array("h", w.readframes(w.getnframes()))
            if sys.byteorder == "big":
                data.byteswap()
            peak_db = 20 * math.log10(peak_of(data) / 32767)
            self.assertAlmostEqual(peak_db, -3.0, delta=0.1)
            self.assertIn("ピーク", buf.getvalue())
            self.assertIn("RMS", buf.getvalue())

    def test_rejects_bad_seconds(self) -> None:
        for value in ("0", "-1", "10000"):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = bgm.main(["--seconds", value, "--out", "/nonexistent/x.wav"])
            self.assertEqual(code, 1, value)
            self.assertIn("--seconds", err.getvalue())


if __name__ == "__main__":
    unittest.main()
