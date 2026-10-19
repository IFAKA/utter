"""Filtering, segmentation and features for short silent-articulation sEMG events."""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, iirnotch, sosfilt, sosfilt_zi, sosfiltfilt, tf2sos

MAINS = 50.0  # Spain
BANDS = [(20, 60), (60, 120), (120, 250), (250, 450)]
N_SUB = 5  # temporal sub-windows per segment
SEG_S = 1.0  # segment length after onset alignment
PRE_S = 0.1


def design(fs: float, lo: float = 20.0, hi: float = 450.0) -> np.ndarray:
    hi = min(hi, 0.45 * fs)
    sos = [butter(4, (lo, hi), "bandpass", fs=fs, output="sos")]
    f = MAINS
    while f < hi:
        b, a = iirnotch(f, 30.0, fs)
        sos.append(tf2sos(b, a))
        f += MAINS
    return np.vstack(sos)


def filt(x: np.ndarray, fs: float) -> np.ndarray:
    """Zero-phase offline filter, x: (n, ch)."""
    return sosfiltfilt(design(fs), x, axis=0)


class OnlineFilter:
    """Causal filter with state for streaming chunks."""

    def __init__(self, fs: float, nch: int):
        self.sos = design(fs)
        self.zi = np.repeat(sosfilt_zi(self.sos)[:, :, None], nch, axis=2) * 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y


def envelope(x: np.ndarray, fs: float, tau_s: float = 0.03, state: float = 0.0) -> np.ndarray:
    """Causal channel-mean RMS envelope (EMA of mean square), (n,). Same in training and live."""
    from scipy.signal import lfilter
    a = np.exp(-1.0 / (tau_s * fs))
    p = np.mean(x**2, axis=1)
    ms, _ = lfilter([1 - a], [1, -a], p, zi=[a * state])
    return np.sqrt(ms)


def channel_ms(x: np.ndarray, fs: float, tau_s: float = 0.03, zi: np.ndarray | None = None):
    """Causal per-channel EMA of x^2: returns (ms (n, ch), final state (ch,))."""
    from scipy.signal import lfilter
    a = np.exp(-1.0 / (tau_s * fs))
    z = (a * (zi if zi is not None else np.zeros(x.shape[1])))[None]
    ms, zf = lfilter([1 - a], [1, -a], x**2, axis=0, zi=z)
    return ms, ms[-1] if len(ms) else (zi if zi is not None else np.zeros(x.shape[1]))


def rest_baseline(x: np.ndarray, fs: float) -> np.ndarray:
    """Per-channel median EMA power over a (mostly rest) filtered recording."""
    return np.median(channel_ms(x, fs)[0], axis=0) + 1e-12


class OnsetDetector:
    """Activity score = mean of the top-3 per-channel power ratios vs rest; onset when the
    score stays above thr for min_s. Used identically for training segmentation and live."""

    def __init__(self, fs: float, base_ms: np.ndarray, thr: float = 4.0, min_s: float = 0.05,
                 tau_s: float = 0.03, top: int = 3):
        self.fs, self.base, self.thr, self.run = fs, np.asarray(base_ms), thr, max(1, int(min_s * fs))
        self.tau, self.top, self.state, self.count = tau_s, top, np.asarray(base_ms).copy(), 0

    def score(self, x: np.ndarray) -> np.ndarray:
        ms, self.state = channel_ms(x, self.fs, self.tau, self.state)
        r = np.sort(ms / self.base, axis=1)[:, -self.top:]
        return r.mean(1)

    def __call__(self, x: np.ndarray) -> int | None:
        """Feed samples; returns onset offset relative to the start of x (may be negative)."""
        found = None
        for i, v in enumerate(self.score(x) > self.thr):
            self.count = self.count + 1 if v else 0
            if self.count == self.run and found is None:
                found = i - self.run + 1
        return found


def find_onset(x: np.ndarray, fs: float, base_ms: np.ndarray, **kw) -> int | None:
    return OnsetDetector(fs, base_ms, **kw)(x)


def segment(x: np.ndarray, fs: float, onset: int) -> np.ndarray:
    """Fixed-length segment starting PRE_S before onset, zero-padded at the end."""
    a = max(0, onset - int(PRE_S * fs))
    n = int(SEG_S * fs)
    s = x[a:a + n]
    if len(s) < n:
        s = np.vstack([s, np.zeros((n - len(s), x.shape[1]))])
    return s


def _td(s: np.ndarray) -> list[np.ndarray]:
    d = np.diff(s, axis=0)
    rms = np.sqrt(np.mean(s**2, 0)) + 1e-9
    wl = np.mean(np.abs(d), 0)
    thr = 0.1 * rms
    zc = np.mean((s[:-1] * s[1:] < 0) & (np.abs(d) > thr), 0)
    ssc = np.mean((d[:-1] * d[1:] < 0) & ((np.abs(d[:-1]) > thr) | (np.abs(d[1:]) > thr)), 0)
    mob = np.sqrt(np.var(d, 0) / (np.var(s, 0) + 1e-12))
    return [np.log(rms), np.log(wl + 1e-9), zc, ssc, mob]


def features(seg: np.ndarray, fs: float, pairs: list[tuple[int, int]] | None = None) -> np.ndarray:
    """Feature vector for one (n, ch) filtered segment.

    Whole-segment TD + band powers per channel, plus log-RMS per temporal sub-window
    (captures articulation timing), normalized by the segment's mean log-RMS so that
    day-to-day gain changes largely cancel.
    """
    if pairs:
        seg = np.hstack([seg, np.stack([seg[:, i] - seg[:, j] for i, j in pairs], 1)])
    f = _td(seg)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))[:, None], axis=0)) ** 2
    freqs = np.fft.rfftfreq(len(seg), 1 / fs)
    tot = spec[(freqs >= 20) & (freqs <= 450)].sum(0) + 1e-12
    for lo, hi in BANDS:
        f.append(np.log(spec[(freqs >= lo) & (freqs < hi)].sum(0) / tot + 1e-9))
    subs = np.array_split(seg, N_SUB)
    sub = np.stack([np.log(np.sqrt(np.mean(s**2, 0)) + 1e-9) for s in subs])  # (N_SUB, ch)
    level = f[0].mean()
    f[0] = f[0] - level
    f[1] = f[1] - level
    f.append((sub - level).reshape(-1))
    return np.concatenate(f)


def feature_names(nch: int, pairs: list[tuple[int, int]] | None = None) -> list[str]:
    chs = [f"ch{i + 1}" for i in range(nch)] + [f"ch{i + 1}-ch{j + 1}" for i, j in (pairs or [])]
    names = [f"{c}:{k}" for k in ("rms", "wl", "zc", "ssc", "mob") for c in chs]
    names += [f"{c}:band{lo}-{hi}" for lo, hi in BANDS for c in chs]
    names += [f"{c}:sub{t}" for t in range(N_SUB) for c in chs]
    return names


def channel_of(name: str) -> str:
    return name.split(":")[0]
