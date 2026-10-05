"""Original dark-ambient soundtrack, synthesized fresh for each Reel (numpy only, no samples).

Layers: minor-key drone with slowly breathing harmonics, a sub "heartbeat", filtered wind,
an inharmonic bell on every slide change, and a low boom on the cover. Everything is
seeded from the post date, so each day sounds different but a re-run is reproducible.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100

# Root notes (Hz) in a low, ominous range, and scale intervals (semitones)
ROOTS = [41.20, 43.65, 46.25, 49.00, 51.91, 55.00, 58.27]   # E1 .. A#1
MODES = {
    "aeolian": [0, 3, 7, 10],
    "phrygian": [0, 1, 7, 10],      # the b2 is pure dread
    "locrian": [0, 3, 6, 10],       # diminished fifth
}


def _env(n, attack, release):
    e = np.ones(n)
    a = min(int(attack * SR), n)
    r = min(int(release * SR), n)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def _drone(t, root, intervals, rng):
    out = np.zeros((2, t.size))
    for k, semi in enumerate(intervals):
        f = root * 2 ** (semi / 12) * (2 if k else 1)
        for ch, detune in enumerate((-0.18, 0.21)):
            fd = f + detune * (k + 1)
            # harmonics whose loudness "breathes" on slow LFOs -> moving filter feel without a filter
            for h in range(1, 9):
                lfo = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.03, 0.11) * t + rng.uniform(0, 6.28))
                amp = (1 / h ** 1.3) * (0.25 + 0.75 * lfo ** (h * 0.6))
                out[ch] += amp * np.sin(2 * np.pi * fd * h * t + rng.uniform(0, 6.28))
    return out / np.max(np.abs(out)) * 0.5


def _pad(t, root, intervals, rng):
    """Mid-register choir-ish pad (175-700 Hz) so the bed is audible on phone speakers."""
    out = np.zeros((2, t.size))
    for k, semi in enumerate(intervals):
        f = root * 2 ** ((semi + 24 + (12 if k % 2 else 0)) / 12)
        swell = (0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.04, 0.09) * t + rng.uniform(0, 6))) ** 2
        vib = 1 + 0.003 * np.sin(2 * np.pi * rng.uniform(4.5, 5.5) * t)
        for ch, det in enumerate((0.997, 1.003)):
            ph = 2 * np.pi * np.cumsum(f * det * vib) / SR
            tone = np.sin(ph) + 0.35 * np.sin(2 * ph) + 0.15 * np.sin(3 * ph)
            out[ch] += tone * swell
    return out / (np.max(np.abs(out)) + 1e-9) * 0.35


def _heartbeat(t, bpm, rng):
    out = np.zeros(t.size)
    beat = 60 / bpm
    for start in np.arange(1.0, t[-1], beat):
        for off, gain in ((0.0, 1.0), (0.24, 0.6)):          # lub ... dub
            i0 = int((start + off) * SR)
            n = int(0.35 * SR)
            if i0 + n >= t.size:
                break
            tt = np.arange(n) / SR
            f = 52 * np.exp(-tt * 6) + 38                         # pitch drops like a kick
            body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 11)
            knock = np.sin(2 * np.pi * np.cumsum(f * 4.2) / SR) * np.exp(-tt * 28) * 0.55
            out[i0:i0 + n] += gain * (body + knock)
    ramp = np.clip(t / (t[-1] * 0.7), 0.25, 1.0)             # grows louder as it goes
    return out * ramp * 0.55


def _wind(n, rng):
    noise = rng.standard_normal(n)
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    band = np.exp(-((np.log(freqs + 1) - np.log(700)) ** 2) / 0.6)   # soft band around 700 Hz
    w = np.fft.irfft(spec * band, n)
    t = np.arange(n) / SR
    gust = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t + rng.uniform(0, 6))) ** 2
    w = w / (np.max(np.abs(w)) + 1e-9)
    return w * gust * 0.12


def _bell(freq, dur, rng):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    sig = np.zeros(n)
    for ratio, amp, decay in ((1, 1, 1.6), (2.76, .5, 2.4), (5.40, .3, 3.5), (8.93, .18, 5), (1.007, .6, 1.4)):
        sig += amp * np.sin(2 * np.pi * freq * ratio * tt + rng.uniform(0, 6)) * np.exp(-tt * decay)
    return sig / np.max(np.abs(sig)) * 0.35


def _boom(dur=3.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = 70 * np.exp(-tt * 2.5) + 28
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 1.6) * 0.9


def _reverb(x, rng, seconds=2.8, mix=0.35):
    n = int(seconds * SR)
    tt = np.arange(n) / SR
    out = np.empty_like(x)
    for ch in range(x.shape[0]):
        ir = rng.standard_normal(n) * np.exp(-tt * 3.2)
        ir[0] = 0
        ir /= np.sqrt(np.sum(ir ** 2))
        size = x.shape[1] + n
        nfft = 1 << (size - 1).bit_length()
        wet = np.fft.irfft(np.fft.rfft(x[ch], nfft) * np.fft.rfft(ir, nfft), nfft)[: x.shape[1]]
        out[ch] = (1 - mix) * x[ch] + mix * wet
    return out


def soundtrack(duration: float, transitions: list[float], seed: int, out_path: Path) -> Path:
    rng = np.random.default_rng(seed)
    n = int(duration * SR)
    t = np.arange(n) / SR
    root = float(rng.choice(ROOTS))
    mode = str(rng.choice(list(MODES)))
    intervals = MODES[mode]

    mix = _drone(t, root, intervals, rng) * 0.7 + _pad(t, root, intervals, rng)
    hb = _heartbeat(t, bpm=float(rng.uniform(54, 66)), rng=rng)
    wind = _wind(n, rng)
    mix += np.vstack([hb, hb]) + np.vstack([wind, np.roll(wind, 900)])

    boom = _boom()
    mix[:, : min(n, boom.size)] += boom[: n]

    bell_pitches = [root * 2 ** ((12 * o + s) / 12) for o in (4, 5) for s in intervals]
    for i, ts in enumerate(transitions):
        b = _bell(bell_pitches[(i * 3) % len(bell_pitches)], 3.5, rng)
        i0 = int(ts * SR)
        seg = b[: max(0, n - i0)]
        pan = 0.5 + 0.35 * np.sin(i * 1.7)
        mix[0, i0:i0 + seg.size] += seg * (1 - pan) * 2
        mix[1, i0:i0 + seg.size] += seg * pan * 2

    mix = _reverb(mix, rng)
    mix *= _env(n, 0.4, 2.0)
    mix = np.tanh(mix * 1.4)                                  # gentle saturation
    mix /= np.max(np.abs(mix)) + 1e-9
    mix *= 0.89                                               # ~ -1 dBFS peak

    pcm = (mix.T * 32767).astype("<i2")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"[audio] {duration:.1f}s soundtrack, root {root:.1f} Hz, {mode} -> {out_path}")
    return out_path
