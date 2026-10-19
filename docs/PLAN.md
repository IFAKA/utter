# Plan

Key facts (sources in docs/SOURCES.md):
- EEG cannot do text (Brain2Qwerty: ~65% CER with EEG).
- Purely imagined speech gives no usable EMG (Meltzner 2008); silently articulated speech does (~87%). User must articulate internally, lips closed.
- Published silent-speech EMG: 68-97% on 8-30 words. LLM suggestions (SpeakFaster, MONA LISA) turn few tokens into text.

## Stages (do not advance until the gate passes)
0. Software only, EUR 0: Mac input-method app, LLM suggestions, earbud voice, keyboard-as-fake-sensor with injected errors; train on Gaddy dataset (Zenodo 4064409). Gate: type a sentence at 80% simulated accuracy; model near published results.
1. Hardware (~EUR 175): shrunken ADS1299+ESP32-S3 neckband, fixed 5V back-feed bug, OPA333 electrode buffers. Gate: shorted-input noise ~<1 uV; clear jaw-clench signal.
2. Record ~16 candidate tokens + rest class, ~100 reps each; keep 8 least confusable. Gate: >80% with lips closed. Fail -> more articulation, then wristband fallback (Meta, Nature 2025).
3. Connect neckband to app: real silent typing in any app.
4. Hide: move electrodes toward ear, 3-minute calibration. Gate: still >80%.
5. Improve: more tokens, speed, Android.

## Decisions
- Start on Mac (Accessibility API typing); Android IME later; iOS keyboards cannot do this well.
- Recognition on host first, ESP32 later.
- "Rest/other" class + wake token to avoid false triggers (chewing, swallowing, talking).
