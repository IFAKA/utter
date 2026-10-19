"""Synthetic silent-articulation sEMG, used to test the pipeline without hardware.

Model: a few "muscle" sources (band-limited noise with their own spectra) project onto
16 electrodes through smooth spatial weights. Each token activates a token-specific
subset of muscles with its own timing. Per-session electrode shift, gain drift, mains
hum and rest artefacts (chew, swallow) make cross-session evaluation non-trivial.
It is a plumbing test, not evidence that real EMG will work.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

N_MUSCLES = 7


class EmgSynth:
    def __init__(self, labels: list[str], nch: int = 16, fs: int = 2000, seed: int = 0,
                 session_seed: int | None = None, amp_uv: float = 12.0, noise_uv: float = 1.5):
        self.labels, self.nch, self.fs = list(labels), nch, fs
        self.amp_uv, self.noise_uv = amp_uv, noise_uv
        rng = np.random.default_rng(seed)  # task structure: same across sessions
        pos = np.linspace(0, 1, nch)
        centers = rng.uniform(0, 1, N_MUSCLES)
        widths = rng.uniform(0.08, 0.25, N_MUSCLES)
        self.spatial = np.exp(-((pos[None] - centers[:, None]) / widths[:, None]) ** 2)  # (M, C)
        self.centers, self.widths, self.pos = centers, widths, pos
        bands = [(30, 120), (50, 200), (80, 300), (40, 160), (100, 400), (60, 250), (30, 90)]
        self.sos = [butter(2, (lo, min(hi, fs / 2 - 1)), "bandpass", fs=fs, output="sos") for lo, hi in bands]
        # token -> list of (muscle, onset_s, dur_s, weight)
        self.patterns = {}
        for lab in self.labels:
            k = rng.integers(2, 4)
            ms = rng.choice(N_MUSCLES, k, replace=False)
            self.patterns[lab] = [(int(m), rng.uniform(0, 0.25), rng.uniform(0.15, 0.4), rng.uniform(0.5, 1.0))
                                  for m in ms]
        self.rng = np.random.default_rng(session_seed if session_seed is not None else seed + 1)
        s = self.rng
        shift = s.normal(0, 0.03)  # electrode placement differs per session
        self.session_spatial = np.exp(-((pos[None] + shift - centers[:, None]) / widths[:, None]) ** 2)
        self.ch_gain = s.uniform(0.7, 1.3, nch)
        self.hum_phase = s.uniform(0, 2 * np.pi, nch)
        self.hum_amp = s.uniform(0.5, 3.0, nch)
        self.t = 0

    def _sources(self, n: int) -> np.ndarray:
        white = self.rng.standard_normal((N_MUSCLES, n))
        return np.stack([sosfilt(self.sos[m], white[m]) for m in range(N_MUSCLES)])

    def _envelope(self, n: int, onset: float, dur: float) -> np.ndarray:
        t = np.arange(n) / self.fs
        return np.clip(np.sin(np.pi * (t - onset) / dur), 0, None) * ((t >= onset) & (t <= onset + dur))

    def background(self, n: int) -> np.ndarray:
        t = (self.t + np.arange(n)) / self.fs
        hum = self.hum_amp[None] * np.sin(2 * np.pi * 50 * t[:, None] + self.hum_phase[None])
        tonic = 0.15 * self.amp_uv * (self._sources(n).T @ self.session_spatial)
        noise = self.noise_uv * self.rng.standard_normal((n, self.nch))
        self.t += n
        return (noise + hum + tonic) * self.ch_gain[None]

    def event(self, label: str, n: int, onset: float = 0.2) -> np.ndarray:
        """n samples containing `label` ("rest", "chew", "swallow" or a token) starting near onset."""
        return self.background(n) + self.activation(label, n, onset)

    def activation(self, label: str, n: int, onset: float = 0.2) -> np.ndarray:
        """Only the event's contribution (no background)."""
        src = self._sources(n)
        env = np.zeros((N_MUSCLES, n))
        speed = self.rng.uniform(0.85, 1.2)
        jitter = self.rng.normal(0, 0.03)
        if label in self.patterns:
            for m, on, dur, w in self.patterns[label]:
                env[m] += w * self.rng.uniform(0.8, 1.2) * self._envelope(n, onset + jitter + on * speed, dur * speed)
        elif label == "chew":
            for m in (0, 1):
                for k in range(3):
                    env[m] += 2.0 * self._envelope(n, onset + 0.3 * k, 0.2)
        elif label == "swallow":
            env[N_MUSCLES - 1] += 2.5 * self._envelope(n, onset, 0.6)
            env[3] += 1.0 * self._envelope(n, onset + 0.1, 0.4)
        return (src * env).T @ self.session_spatial * self.amp_uv * self.ch_gain[None]
