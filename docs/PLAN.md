# Plan

Key facts (sources in docs/SOURCES.md):
- EEG cannot do text (Brain2Qwerty: ~65% CER with EEG).
- Purely imagined speech gives no usable EMG (Meltzner 2008); silently articulated speech does (~87%). User must articulate internally, lips closed.
- Published silent-speech EMG: 68-97% on 8-30 words. LLM suggestions (SpeakFaster, MONA LISA) turn few tokens into text.

## Stages (do not advance until the gate passes)
0. Software only, EUR 0: Mac input-method app, LLM suggestions, earbud voice, keyboard-as-fake-sensor with injected errors; train on Gaddy dataset (Zenodo 4064409). Gate: type a sentence at 80% simulated accuracy; model near published results.
0.5. Signal check before buying the board (research pass 2026-10-19, see below). Gate: user decides between (a) order Utter, (b) EUR ~130 Cyton clone pilot first, using the lips-closed vs mouthed comparison.
1. Hardware (~EUR 225-255): own Utter board, 2x ADS1298 = 16 ch + ESP32-S3, battery only, JLC-assembled (docs/HARDWARE.md, order card docs/ORDER.md). Gate: shorted-input noise ~<1 uV; clear jaw-clench signal.
2. Record ~16 candidate tokens + rest class, ~100 reps each; keep 8 least confusable. Gate: >80% with lips closed. Fail -> more articulation, then wristband fallback (Meta, Nature 2025).
3. Connect neckband to app: real silent typing in any app.
4. Hide: move electrodes toward ear, 3-minute calibration. Gate: still >80%.
5. Improve: more tokens, speed, Android.

## Decisions
- Start on Mac (Accessibility API typing); Android IME later; iOS keyboards cannot do this well.
- Recognition on host first, ESP32 later.
- "Rest/other" class + wake token to avoid false triggers (chewing, swallowing, talking).

## Research pass 2026-10-19 (gaps)
- Lips closed, no movement: no study found that tests it. All results below are silent articulation (mouth moves, no sound). Treat lips-closed as unproven and probably worse. Stage 2 is the first real test.
- Closed vocab: 88-97% (100 words/28 subjects 90.8% Frontiers 2022; single subject 97% ScienceDirect 2024; 5-ch decision tree 95%). Silent EMG alone 72% in one fusion study (World Scientific 2025).
- Open vocab, Gaddy & Klein: 68% -> 42.2% WER (ACL 2021), one speaker, 19 h of data; later work claims <10% with LLM post-correction (Benster 2024, unverified). Real open-vocab needs hours of data per user and mouth movement. Not a 12-minute x4 sessions job.
- Cheap pilots exist: 8-ch OpenBCI Cyton at 250 Hz with 8 words (MindScribe 2025, IIT Kanpur 9.3% WER on face electrodes). 250 Hz is below the 1-2 kSPS this board targets, so a Cyton pilot shows feasibility but not our final accuracy.
- Consequence: keep the 8-token + LLM design; open-vocab is a Stage 5 stretch needing hours of per-user recording.

## Typing-efficiency benchmark (2026-10-19)
`app/.build/release/st-gate --llm [--corpus chat|agent] [--context] [--phrases] [--browse N] [--quick-pick]`, gemma3:1b, gestures per word (≈ wpm at 1.5 s/gesture):

| Setup | 100% recognition | 90% | 80% |
|---|---|---|---|
| Chat, current decoder | 3.25 (12.3) | 4.10 (9.8) | 5.87 (6.8) |
| Chat, user also takes the 2nd suggestion (na ya) | 3.17 | 4.14 | 5.28 |
| Chat, quick-pick (na + key = suggestion 3-6) | 3.11 | 3.98 | 5.40 |
| Agent replies, LLM sees only the reply | 5.34 (7.5) | 7.64 | 11.34 |
| Agent replies, LLM sees the agent's last message | **3.82 (10.5)** | **4.64** | **5.76** |
| ... plus quick-pick | 3.62 | 4.55 | 5.83 |
| ... plus whole-reply suggestions (gemma3:1b) | 3.85 | 4.65 | 7.96 |

Conclusions:
- Agent context is the one big win: −39% gestures at 90%. The app must receive the agent's last message, e.g. from a Claude Code Stop hook.
- Quick-pick gains only 3-5% and adds a mode, so it stays off.
- Whole-reply suggestions from a 1B model are generic ("yes please"), so there is no measurable gain. Revisit with a larger model or the agent's own suggested prompts. The benchmark only counts exact matches, which undervalues equivalent replies.
- Permission prompts (approve / reject) should map directly to ya / sha: one gesture. Not built yet.
