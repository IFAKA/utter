# Plan

Key facts (sources in docs/SOURCES.md):
- EEG cannot do text (Brain2Qwerty: ~65% CER with EEG).
- Purely imagined speech gives no usable EMG (Meltzner 2008); silently articulated speech does (~87%). User must articulate internally, lips closed.
- Published silent-speech EMG: 68-97% on 8-30 words. LLM suggestions (SpeakFaster, MONA LISA) turn few tokens into text.

## Stages (do not advance until the gate passes)
0. Software only, EUR 0: Mac input-method app, LLM suggestions, earbud voice, keyboard-as-fake-sensor with injected errors; train on Gaddy dataset (Zenodo 4064409). Gate: type a sentence at 80% simulated accuracy; model near published results.
0.5. Signal check before buying the board (research pass 2026-10-19, see below). Gate: user decides between (a) order Utter, (b) EUR ~130 Cyton clone pilot first, using the lips-closed vs mouthed comparison.
1. Hardware (~EUR 225-255): own Utter board, 2x ADS1298 = 16 ch + ESP32-S3, battery only, JLC-assembled (docs/HARDWARE.md, order card docs/ORDER.md). Gate: shorted-input noise ~<1 uV; clear jaw-clench signal.
2. Record the 16 lips-closed candidates (tongue/jaw gestures + silent syllables, see "Command set for lips closed") + rest class, ~100 reps each; keep 8 least confusable. Gate: >80% with lips closed. Fail -> more articulation, then wristband fallback (Meta, Nature 2025).
3. Connect neckband to app: type in any app by mouthing words.
4. Hide: same layout on a velcro textile band with dry snap electrodes (SilentWear), 3-minute calibration. Gate: still >80%, within ~5 points of gel.
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

## Keyboard-first vs app (2026-10-20)
Decision (updated): everything runs on the device. The wearable is a standalone BLE HID keyboard with no companion app on any host. The Mac app is kept only as a development simulator (`keysim`, `st-gate`, benchmarks), not a product component.

Consequences:
- Lost without a host: LLM suggestions (-39% agent-context gain), spoken suggestions, and the Claude Code hook. Accepted for zero-setup use on any device.
- ACCEPT / BACK (default ka / jaw drop) become plain tokens mapped to Return / Escape (or y / n) by the firmware, so approving prompts works in any agent or app without a hook.
- Decoding quality now depends on the on-device scorer (dictionary + bigram, or a ~1 MB neural model). That is the main thing to build and measure.

- Today the wearable is only a sensor and all decoding is in the Mac app, so it is not a drop-in keyboard. That was a software-phase shortcut.
- On the ESP32-S3: signal -> token classifier (8 classes) and a dictionary/n-gram word decoder fit. The LLM, screen context and agent hooks need a host. Suggestions need an output channel (earbud audio).
- Dictionary-only vs LLM, chat corpus, gestures (tokens) per word (`st-gate --corpus chat` vs `--llm`; the LLM column is from the benchmark above and was not re-run):

| Recognition | Dictionary only (60k words) | With LLM | Dictionary cost |
|---|---|---|---|
| 100% | 5.06 (7.9 wpm) | 3.25 (12.3 wpm) | +56% |
| 90% | 6.31 (6.3 wpm) | 4.10 (9.8 wpm) | +54% |
| 80% | 8.69 (4.6 wpm) | 5.87 (6.8 wpm) | +48% |

- Dictionary-only passes the Stage 0 gate (>=95% sentences at 80% token accuracy) but costs about 50% more gestures. Untested: a tuned on-device lexicon (smaller vocabulary, bigrams, personal frequencies) may narrow the gap.
- The agent-context gain (-39% gestures) exists only in the app.
- Next: build and measure the bigram/neural scorer below.

### On-device feasibility research (2026-10-20)
Board is ESP32-S3-WROOM-1-N8: 8 MB flash, no PSRAM, 512 KB SRAM, BLE only (no Bluetooth Classic, so no A2DP earbud audio from the wearable).
- Prior art fits: Gboard's next-word model is a 1.4M-parameter CIFG-LSTM, 10k vocab, 1.4 MB quantized (Hard et al. 2018, arXiv 1811.03604). AOSP LatinIME uses a Patricia-trie `.dict` with per-word frequency and bigram tables; 100k words is about 3-5 MB, and bigrams can multiply size (HeliBoard discussion). A 1.4 MB model fits in 8 MB flash; read-only weights run from flash.
- Speed trap avoided: Dogberry (LSTM, 256 cells, 4000-word softmax) runs only 1-2 words/s on ESP32-S3, dominated by the full-vocabulary dense layer. We never need that: ambiguous-token decoding scores only the 10-50 words matching the token pattern, so the output layer is a handful of dot products (my estimate, not measured).
- Bigram gain on ambiguous keypads is real but modest on conversational text: HMS bigrams cut KSPC 1.081 -> 1.011 on SMS and 1.009 -> 0.881 on news. Expect part of the 50% gap to close, not all. Measure it.
- BLE HID is one-way: the host never tells the device what is in the text field, and autocorrect or cursor moves desync any context (Bluke PR #13, InputStick docs). Design rules: keep context only from what the device itself typed, reset it on pause, Enter or a long idle, and correct by backspace-and-retype of the last word only.
- No screen and no BLE audio means suggestions can't be spoken from the wearable. Use T9-style in-field feedback instead: type the top candidate at once, and a "next" gesture backspaces and retypes the next candidate. This needs only one-way HID. Spoken suggestions stay a host-app feature.
- ESP32 BLE HID libraries exist (NimBLE-Arduino, T-vK/ESP32-BLE-Keyboard, HijelHID_BLEKeyboard); a 3-host switcher on ESP32-S3 exists (osrtos). Recommended HID params: 7.5-15 ms connection interval, slave latency 0. Per-host bond storage in NimBLE is unverified.
- Silent-speech context: MONA LISA (Benster 2024) reaches 12.2% WER on Gaddy with 4-gram + LLM rescoring, so n-gram plus LM rescoring is the established approach, but it is host-side. It is open-vocabulary and not directly comparable to our 8-token design.

On-device bigram result (2026-10-20): `st-gate --corpus chat --ngram DIR [--keep N] [--learn]`, `TypingCore/NgramPredictor.swift`, Norvig Google-web counts (norvig.com/ngrams count_1w.txt + count_2w.txt), gestures/word:

| Recognition | Dictionary only | Bigram, keep 20 (~100k pairs, ~300 KB) | Bigram, keep 100 (153k pairs) | Host LLM |
|---|---|---|---|---|
| 100% | 5.06 | 4.59 (-9%) | 4.50 (-11%) | 3.25 |
| 90% | 6.31 | 5.71 (-10%) | 5.73 (-9%) | 4.10 |
| 80% | 8.69 | 7.95 (-9%) | 8.44 (-3%, noisy) | 5.87 |

- Bigrams close about a third of the dictionary-to-LLM gap; keep 20 is as good as keep 100, so ~300 KB of flash is enough.
- Personal learning (`--learn`, online, each sentence learned after it is typed, weight 0.3-0.5) gives no measurable gain here (4.56 at 100%): the 40 test sentences share almost no bigrams. Real users repeat themselves far more; needs a longitudinal test.
- The remaining gap is context length (the LLM sees the whole sentence, the bigram one word). Next lever: a Gboard-class tiny LSTM (~1.4M params, ~1.4 MB int8) trained on conversational text, scoring only the candidates that match the token pattern.

On-device neural result (2026-10-20): `ml/utter/lm.py` word LSTM (10k vocab, E 96 tied, H 256, 1.36M params, 1.44 MB int8), trained 3 epochs (~12 min, MPS) on 2M sentences of SODA valid split (allenai/soda, CC-BY-4.0); 2,435 training sentences identical to benchmark strings were dropped. Val ppl 17. `st-gate --corpus chat --neural ml/data/lm`, gestures/word:

| Recognition | Dictionary | Bigram (~300 KB) | Neural LSTM (1.44 MB) | Host LLM (gemma3:1b) |
|---|---|---|---|---|
| 100% | 5.06 | 4.59 | **3.76** | 3.25 |
| 90% | 6.31 | 5.71 | **4.82** | 4.10 |
| 80% | 8.69 | 7.95 | **6.69** | 5.87 |

- The tiny LSTM closes ~70% of the dictionary-to-LLM gap and fits the N8 flash. Caveat: benchmark replies are common phrases; exact duplicates were removed but near-duplicates in SODA may flatter the score. Next: a held-out benchmark written independently of the training data, and the coding-chat domain (SODA is social chat).
- Device cost: one LSTM step is ~0.36M int8 MACs per word plus scoring only the code-matching candidates (not the 10k softmax); expected to be milliseconds on the S3 vector unit (estimate; whistle-esp32 shows int8 PIE kernels in plain C99).

Prior art (2026-10-20 search): nobody ships the whole thing (silent-speech tokens -> on-device LM -> BLE HID keyboard, open source). Closest pieces:
- SilentWear (ETH/Bologna, arXiv 2603.02847, open code + data): 14-ch textile neck EMG, on-device 15k-param CNN, 8 commands, 77.5% silent within session, 59.3% across sessions, >10% recovered with <10 min fine-tuning. Our token classifier's nearest reference; its cross-session drop is our main recognition risk.
- AlterEgo (MIT spin-out, launched Sep 2025): closed, commercial, no public numbers.
- 3-Key-Input (arXiv 2606.11642): 2-5 keys + LM decoding; letter-to-key mapping barely matters (+0.5 pp CER). Supports the 4-group design.
- SpeakFaster (Google, ALS eye-gaze users): abbreviated entry + LLM saved 57% motor actions; AAC LLM vs n-gram gives +5.5% keystroke savings (arXiv 2501.10582).
- whistle-esp32 (Apache-2.0): voice speech-to-text on an ESP32-S3 N16R8, 14.5 MB model, ~6 s latency. Not our input (voice, not EMG) and needs PSRAM, but its int8 PIE C99 kernels are a template for running our LSTM.

Independent benchmark (2026-10-20): `st-gate --corpus fresh` is 48 sentences written without looking at any training data (care needs, everyday messages, coding chat). Decoder fix in the same pass: candidates were capped at 20, so some valid lexicon words could never be reached; now every exact-length match follows the top 20 (`Decoder.refresh`). The chat numbers did not change. Gestures/word:

| Recognition | Dictionary | Bigram | Neural LSTM |
|---|---|---|---|
| 100% | 5.58 | 5.35 (-4%) | 5.19 (-7%) |
| 90% | 8.54 | 7.63 (-11%) | 7.22 (-15%) |
| 80% | 11.30 | 11.11 (-2%) | 11.56 (+2%) |

- On unseen text the LM gains mostly vanish: 2-15% instead of 9-26%. The chat benchmark was flattered by stock phrases that SODA is full of. The LSTM is still the best at 90-100%, but on-device LM choice is a second-order lever.
- The gate fails (44/48 at 80%) for one reason only: 3 words are not in the lexicon ("armrest", "utils", "readme"), so they can never be typed. **A spell mode for out-of-vocabulary words is required**, plus adding typed OOV words to the personal lexicon. That matters more than any LM upgrade.
- Fixed (2026-10-20) with **letter mode**:
  - A spell marker (✎) is always the last candidate. Accepting it switches to letters: each group token types the likeliest letter of that group given the letters so far, from a character 4-gram trained on the lexicon (`TypingCore/Speller.swift`). NEXT swaps the last letter for the next likeliest in its group, BACK deletes a letter (or leaves the mode), and ACCEPT types the word.
  - Accepted out-of-lexicon words are learned and offered like dictionary words from then on.
  - Whole-word guessing (beam search over the char model) was tried first. It recovered only "utils"; for 7 letters, 4 groups allow ~6.5^7 strings, so it cannot guarantee reach. Letter mode can.
  - Fresh corpus, dictionary only, with letter mode, gestures/word and sentences typed:

    | Recognition | Gestures/word | Sentences typed |
    |---|---|---|
    | 100% | 5.78 | 48/48 |
    | 90% | 8.42 | 48/48 |
    | 80% | 10.47 | 44/48 |

    Every word is now reachable.
  - Remaining 80% failures: three are dictionary words ("wipe", "logs", "api") that ran out of the 6x gesture budget after random errors, and one is "readme", which ended one letter off in letter mode. The gate now measures error recovery, not coverage.
- Recognition dominates: going from 80% to 90% recognition saves 24-38% gestures, more than any LM change.

## SilentWear real-data check (2026-10-20)
`ml/utter/silentwear.py` runs our live pipeline (`dsp.features` + LDA/SVM) on the open SilentWear dataset (HF PulpBio/SilentWear: 14-ch neck EMG, 500 Hz, 4 subjects x 3 days x 5 silent batches, 8 words + rest, 9 classes, 1.4 s windows, chance 11%), using the paper's splits. `ml/utter/speechnet.py` is a port of their SpeechNet CNN (Apache-2.0, paper config) on the same splits and the same calibration trials.

| Subject | Model | Within session | Next day, no calibration | +3/class (~1.5 min) | +14/class (~7 min) |
|---|---|---|---|---|---|
| S01 | LDA / SpeechNet | 74.8 / **80.8** | 48.4 / **65.5** | 60.2 / **73.6** | 70.3 / **79.5** |
| S02 | LDA / SpeechNet | 71.4 / **79.8** | 44.3 / **65.5** | 58.5 / **76.2** | 66.9 / **78.6** |
| S03 | LDA / SpeechNet | 65.2 / **69.3** | 48.2 / **60.9** | 57.0 / **65.0** | 62.1 / **65.8** |
| S04 | LDA / SpeechNet | 65.2 / **66.7** | 50.7 / **60.9** | 58.8 / **63.7** | 63.7 / **66.3** |
| Mean | LDA | 69.2 | 47.9 | 58.6 | 65.7 |
| Mean | SVM | 67.3 | 46.4 | 55.1 | 62.6 |
| Mean | **SpeechNet** | **74.2** | **63.2** | **69.6** | **72.6** |
| Paper | SpeechNet | 77.5 | 59.3 | - | 72 after 1 round, 79 after 5 |

- **Switch the token classifier to SpeechNet.** It beats our features+LDA everywhere, most where it matters: next-day accuracy goes from 48% to 63% (+15 points), and from 59% to 70% with 3/class calibration. Our port reproduces the paper (cross-day is even a bit higher; ours is their architecture with our random calibration draw).
- The CNN is 15,489 params. That is ~15 KB int8, trivially small for the ESP32-S3; the cost is the convolutions over 14x700 samples per window, to be measured on the chip.
- It is still short of the 80% the gate needs. Next levers, cheapest first:
  - Calibrate on a whole batch, as the paper does (their 5 fine-tuning rounds reach 79%).
  - Fine-tune online on tokens the user confirmed (ACCEPTed words imply the right tokens).
  - Augment: amplitude scaling and channel-shift, against electrode drift between days.
  - Pre-train on all other subjects, then fine-tune (the subject-scaling experiment in their repo).
- Calibration time scales: 9 classes x 3 trials x ~3.5 s is about 1.5 min; 14/class is about 7 min.
- Practical note: training uses MPS. torch's CPU conv (NNPACK) is ~12x slower here for the 1xk kernels.

### Closing the next-day gap (2026-10-20, `ml/utter/crossday.py`)
Leave-one-day-out, mean of 4 subjects. "AdaBN" re-estimates BatchNorm statistics on the new day's unlabeled windows (free on the device). "Online" simulates learning while typing: the day's 5 batches (180 tokens, ~30 words each) arrive in order; after each, fine-tune on all confirmed tokens so far and test on the next batch.

| Variant | Zero-shot | Top-2 | AdaBN | Online after 1 / 2 / 3 / 4 batches |
|---|---|---|---|---|
| Plain SpeechNet | 62.2 | 80.5 | 67.9 | 65.1 / 70.6 / 73.8 / 73.7 |
| + per-day channel normalization + augmentation | 70.5 | 86.7 | 74.8 | 78.1 / 76.1 / 82.6 / 82.4 |
| + pre-train on the other 3 subjects (fine-tune lr 3e-4) | **72.1** | 87.3 | **75.8** | **80.8** / 80.7 / 83.8 / 84.5 |

- Normalization + augmentation is the big win (+8 zero-shot, +9 online); keep both. Not yet ablated separately.
- Cross-subject pre-training adds ~1-3 points (confounded with the lower fine-tune lr). For Utter this needs other Utter users' data (SilentWear's weights do not transfer: different electrodes and channel count), so it is a later gain.
- Plain online fine-tuning at lr 1e-3 first drops (65.1 < 67.9): too aggressive on 180 trials.

### Gate with the real recognizer (st-gate `--confusions`)
`crossday --dump` writes SpeechNet's softmax for every held-out trial; st-gate replays them (sampled per intended action) instead of the synthetic "correct with probability p" model. Fresh corpus, 48 sentences, 4 seeds:

| Condition | Sentences typed | Gestures/word |
|---|---|---|
| Next day + AdaBN (74.8%), alphabetical word→action | 40-41/48 | ~14.4 |
| Same, confusion-aware word→action mapping | 42-44/48 | ~15.5 |
| + reject tokens below 0.7 confidence (user repeats) | **48/48 x4** | 16.6 |
| After ~60 typed words of online learning (80.3%), p-min 0.7 | 191/192 | 11.6 |
| p-min 0.6 / 0.8 / 0.9 (next day) | 188 / 189 / 144 of 192 | 15.6 / 20.3 / 31.4 |

- **The gate passes on real next-day errors.** Two cheap fixes did it: (1) the worst confusions (start/stop, up/down/left) were landing on ACCEPT/BACK; `train.assign_actions` now picks the mapping with the lowest expected confusion cost from each user's confusion matrix; (2) confidence rejection at 0.7 (engine `p_min` default raised from 0.6), since a missed token costs one repeat while a wrong ACCEPT costs a delete and retype.
- 15% of letter-group tokens were misread as a control action, the costliest error; rejection removes most of it.
- Soft decoding (the decoder ranks words with the recognizer's group probabilities) gave no gain on 4 seeds at any weight, so it was removed.
- The price is speed: ~16.6 gestures/word on day 1 morning, ~11.6 after an hour of use (≈2.4-3.4 wpm at 1.5 s/gesture). The next speed levers are the 0.8 s window, online learning, and LM quality.
- Caveats: SilentWear's 8 words are not our tokens (we pick our 8 from ~16 candidates, so confusions should be lower); sampling ignores within-session temporal correlation; rest false-alarms during idle time are not simulated.

### 0.8 s window (2026-10-20, `crossday --window 0.8`)
Same pipeline (norm + augmentation), 0.8 s windows instead of 1.4 s. Mean of 4 subjects, next day:

| Window | Zero-shot | Top-2 | AdaBN | Online after 4 batches |
|---|---|---|---|---|
| 1.4 s | 70.5 | 86.7 | 74.8 | 82.4 |
| 0.8 s | 66.3 | 84.4 | 69.2 | 75.1 |

st-gate, fresh corpus, 48 sentences x 4 seeds, p-min 0.7, own confusion-aware mapping, 1.5 s/token (1.4 s) vs 0.9 s/token (0.8 s):

| Condition | Window | Sentences typed | Gestures/word | wpm |
|---|---|---|---|---|
| Next day + AdaBN | 1.4 s | 192/192 | 16.8 | 2.4 |
| Next day + AdaBN | 0.8 s | 180/192 (fails gate) | 23.7 | 2.8 |
| After online learning | 1.4 s | 191/192 | 11.6 | 3.4 |
| After online learning | 0.8 s | **192/192** | 14.8 | **4.5** |

- Shorter windows are less accurate (-4 to -7 points), so each word needs more gestures, but each gesture is ~40% faster, so the net is faster.
- On a fresh morning, 0.8 s fails the gate (180/192); raising p-min to 0.75/0.8 makes it worse (175/138 of 192).
- After online learning, 0.8 s passes and is ~1/3 faster (4.5 vs 3.4 wpm).
- **Decision: adaptive window.** Start each session at 1.4 s; switch to 0.8 s once online learning has caught up (about an hour of use / when confirmed-token accuracy is above ~75%). Untested assumption: 0.1 s overhead per token on top of the window.

### Word prediction for chat + coding (2026-10-20, `ml/data/lm-code`)
Same LSTM (1.44 MB int8), retrained on 463k plain-English sentences from coding requests (m-a-p/CodeFeedback-Filtered-Instruction user queries, Apache-2.0; code lines dropped) + SODA chat up to 2M sentences. Val ppl 22 (mixed text; the chat-only model's 17 is on easier text). st-gate with real next-day errors (1.4 s, AdaBN, p-min 0.7), 4 seeds, gestures/word:

| Corpus | No prediction | Chat LSTM (`data/lm`) | Chat + coding LSTM (`data/lm-code`) |
|---|---|---|---|
| Fresh everyday sentences (40) | 15.6 | 14.1 | **13.6** |
| Replies to a coding agent (25) | 19.0 | 18.3 (2 sentences failed) | **15.4** (all typed) |

- Coding replies need 16% fewer gestures with the new model, and everyday chat does not get worse. Use `data/lm-code` as the on-device model.
- Bug found and fixed: Ollama unloads the model after 5 idle minutes; reloading (~6 s) outlasted every 1 s request and was cancelled with it, so the LLM silently returned nothing. `OllamaPredictor.warmUp()` + `keep_alive` 2h (app and st-gate).

### Replying to a coding agent with real errors (2026-10-20, `st-gate --corpus agent`)
25 replies to agent messages, 4 seeds, real recognizer outputs. "Morning" = next day + AdaBN, 1.4 s window, 1.5 s/token. "Learned" = after online learning, 0.8 s window, 0.9 s/token.

| Predictor | Morning: gestures/word, wpm | Learned: gestures/word, wpm |
|---|---|---|
| Dictionary only | 19.0, 2.1 | 17.1, 3.9 |
| On-device chat+coding LSTM | 15.2, 2.6 | 14.0, 4.8 |
| LLM (gemma3:1b), no context | 16.0, 2.5 | 13.6, 4.9 |
| LLM reads the agent's message | **10.6, 3.8** | **8.9, 7.5** |
| + whole-reply suggestions | 10.6, 3.8 | 8.8, 7.6 |

- The biggest lever is letting the LLM read what the agent said: about 40% fewer gestures than without context. With the 0.8 s window after learning, this reaches ~7.5 wpm, inside the 5-9 wpm range of one-key scanning keyboards (MacKenzie 2009).
- Whole-reply suggestions add almost nothing with gemma3:1b: they matched the exact reply only 2/25 times (often close: "create a pull request" for "open a pull request"). Before the fix below they never appeared at all: the 1B model answered "yes / okay / sure". `phrases()` now uses a one-example prompt that yields real multi-word replies in ~0.2 s.
- Next levers for replies: (1) remember the user's own past replies as phrase candidates ("go ahead", "commit the changes" repeat in real use; Tanaka-Ishii 2002's user corpus); (2) a larger local model for phrases; (3) accept the shared start of a near-miss phrase. (1) needs real use to measure.

### Reply memory and the offline word model (2026-10-20)
- Offline: the app now ships the chat + coding LSTM (`TypingCore/Resources/lm`, `NeuralPredictor.bundled()`). Without Ollama it predicts with that instead of nothing (19.0 -> 15.2 gestures/word on agent replies, morning). English only; Spanish still falls back to no prediction.
- Reply memory (`ReplyMemory.swift`) wraps any predictor and saves every sent reply with the agent message it answered (`~/Library/Application Support/Utter/replies.jsonl`, local only). It offers them two ways:
  - whole, before the first word, when the agent's message shares enough content words (Jaccard >= 0.25) with one you answered before;
  - as the rest of the reply once you've typed its first words ("yes" -> "run the tests"), placed second so a wrong one costs at most one NEXT.
- Measured with `st-gate --corpus agent --memory 2 [--reword] [--no-offers]`, real recognizer errors, mean of seeds 1-2, gestures/word:

| | New user (pass 1) | Same questions again | Same questions, other words | Other words, memory off |
|---|---|---|---|---|
| Offline LSTM, morning | 15.2 | 1.0 | **13.5** | 15.2 |
| Offline LSTM, after learning | 14.0 | 1.0 | **12.0** | 14.0 |
| LLM + context, morning | 10.3 | 1.1 | **11.6** | 11.9 |
| LLM + context, after learning | 9.0 | 0.9 | **9.9** | 10.3 |

- In simple words: memory never costs a new user anything (pass 1 is identical to no memory). An identical question makes a remembered reply almost free. When the agent asks the same thing in other words, the memory rarely matches the whole message (word overlap is weak for rewordings), but the completions after the first word still save 5-14%.
- Rewordings, filled: like Smart Reply, the memory now also compares agent messages by meaning, with a small sentence-embedding model through Ollama (`all-minilm`, 46 MB, English; `ReplyMemory.embed`, `st-gate --embed`). Similarity is the larger of word overlap and cosine - 0.2, so one threshold serves both. On the 25 rewordings, the closest stored message by cosine is the right one 24 times (word overlap: almost never). At cosine >= 0.45, 20 of 25 are offered, with 1 wrong offer; when the reply was never remembered, 2 of 25 get a wrong offer (it costs one NEXT).

| LLM + context, other words | Memory, word overlap | Memory + embeddings |
|---|---|---|
| Morning | 11.3 | **5.7** |
| After learning | 10.1 | **4.7** (~15 wpm) |

- In simple words: when the agent asks the same thing in other words, your old reply now usually shows up anyway, which halves the work. Caveats: the 0.45 threshold was picked on these same 25 rewordings, so the real gain will be somewhat lower; and with hundreds of remembered replies, wrong offers will be more common than here. Embeddings need Ollama (they are off with the offline model and in the demo). How often a real user repeats replies decides how much any of this is worth: only daily use can tell.
- The demo site (`docs/demo.html`) now runs the same offline model in the browser (`assets/lm.js`, identical predictions to the Swift one) without the 137 MB download, and the same reply memory in `localStorage`, with a "Forget" link.

## Command set for lips closed (2026-10-21)
The first candidates (ka ta la ga na ya sha ree too kee tik dog lulu chee ung eek) had no written basis, and several need visible lips (sha, too, dog, lulu, chee, eek). Silent speech has no voicing, so ka/ga were one movement. Evidence found:
- Tongue gestures inside a closed mouth are the best-proven discrete input: 6 motions (up, down, left, right, forward, swallow) at 95.1% from suprahyoid sEMG under the jaw, 5 adults (Sasaki et al., ROBOMECH J. 2016, doi:10.1186/s40648-016-0048-0); TongueSee 6 gestures 94.2% with a preamble for low false positives (CHI 2014, doi:10.1145/2556288.2556981); tongue left/right/up + jaw opening + clenching 92.0%, 72.8% after an electrode shift, 90.4% when trained over several positions and days (Mech. Eng. J. 2019, doaj c0dce470acf14d06917fb1d539f06331).
- Silent words on a neckband: SilentWear 77.5% within a day, 59.3% across days, 8 words, short commands worst; mouthing protocol not stated (arXiv 2603.02847). Internal articulation without visible movement: AlterEgo 92% median on digits, with face/jaw electrodes (IUI 2018).
- Decision: 16 candidates = 7 lips-closed tongue/jaw gestures (tongue up/down/left/right/push, jaw drop, clench) + 9 silent syllables with no lip action (revised the same day, see below). Recording keeps the 8 the band separates best (`train.pick_tokens`) and maps the costly actions to the least-confused ones (`train.assign_actions`). Swallow and chew stay in the rest class: people swallow often, so they must never trigger.
- Defaults until a user's first recording: G1-G4 tongue up/down/left/right, NEXT tongue push, ACCEPT ka, BACK jaw drop, WAKE clench.
- Gap: the proven tongue results read the suprahyoid muscles under the jaw; our band reads the infrahyoid muscles and SCM (after SilentWear). Whether the neckband sees tongue gestures as well is unproven. Test at the gel signal-ceiling session: record the 16 candidates with the standard layout and with one row moved under the chin, compare `pick_tokens` accuracy.
- Syllables revised (2026-10-21): the first 9 (ka ta la na sa ya ree ung tha) mostly differed only in where the tongue touches; na/sa share the spot of ta, ung that of ka, and without voice or airflow the nasal and the hiss are gone. On the neck that is the weakest contrast: a magnetometer necklace reading silent speech (Dash et al., bioRxiv 2025.08.04.668236, stimuli from the EMG necklace, Wu et al. arXiv 2407.21345) reached ~71%, with most errors among ada/aga/aka (place only), while vowel-contrast words (heed/had/hood) separated; EMG-necklace errors were also same-manner stops (k/t, d/b). So each syllable now differs from the others in the vowel (tongue height and frontness, which moves the hyoid) and, where possible, the consonant too: ka tee loo yah ree thuh ee oo aw. ka stays (the one back-of-tongue closure). Lips stay closed and still for oo/loo: only the tongue moves back. Still a reasoned set, not a measured one; `pick_tokens` on the first recording decides.

### Letter groups: alphabetical split kept (2026-10-21)
Gong & Tarasewich (CHI 2005, doi:10.1145/1054972.1055002) found optimized alphabetical groupings close to unconstrained ones and easier to learn, so only split points were searched. All 2,300 alphabetical 4-way splits scored on the 20k word list without context: the best (abcde/fghijkl/mnopqr/stuvwxyz) saves 0.03 NEXT per word (0.445 -> 0.417). With the word model (`st-gate`, fresh and chat corpora) the top three splits are within 1% of the current one at 100% token accuracy and equal or worse at 80% (fresh 9.63 gestures/word now vs 10.31-12.53). The language model already resolves the ambiguity; abcdef/ghijklm/nopqrs/tuvwxyz stays.

## What we took from pulp-bio (2026-10-20)
Reviewed: SilentWear (dataset + code), BioGAP-Ultra hardware (the SilentWear system diagram), TinyProbe, BioFoundation.
- **SilentWear dataset: used.** It is the only open silent-speech EMG set with several days per subject, so it lets us test cross-day recognition before ordering hardware (results above).
- **SilentWear SpeechNet: ported** (`utter/speechnet.py`). It is ~15k params and 8-bit on device, on raw filtered windows with no hand-made features, which fits the ESP32-S3 (their 14x400 int8 input is ~5.6 KB). Their fine-tuning protocol (whole net, lr 1e-3, 50 epochs on the new day's trials) is copied too.
- **SilentWear protocol ideas adopted:**
  - Report within-session and cross-day separately: the cross-day number is what users feel.
  - A short re-calibration each time the band is put on (they use ~10 min, 70% of one batch). Our Stage 4 "3-minute calibration" is the same idea, and 3/class versus 14/class shows the tradeoff.
  - A 0.8 s on-device window (versus 1.4 s offline): shorter windows mean faster tokens. Test it in our bench.
- **BioGAP-Ultra hardware: confirms our design, nothing to copy.**
  - It uses the same 2x ADS1298 AFE as Utter, with differential channels, a MEMS oscillator (SIT8021) and an IMU (LIS2DU).
  - Its compute (GAP9 + nRF5340) is costlier and harder to source than our ESP32-S3, and SpeechNet is small enough not to need GAP9.
  - Their IMU is a reminder to keep ours for motion-artefact rejection.
- **Neck electrode layout: adopted (2026-10-20).** SilentWear's band, from their paper: 27 dry Datwyler SoftPulse snaps on a velcro textile band; 15 front electrodes in 3 rows give 10 vertical bipolar channels over the infrahyoid muscles (best SNR), 2 bipolar pairs per side over the sternocleidomastoid, 4 shorted ground electrodes at the back of the neck. No tightness spec; their worst session was blamed on loose contact, so the band must sit snug with padding behind the front grid. Ours (ml/utter/neckband.py): 3 x 4 front grid + 2 per SCM = 16 monopolar inputs, 13 bipolar pairs in software, REF/RLD at C7. Open: the paper never says whether lips moved ("silent" = no vocalization); ALS weakening of neck muscles is untested; swallowing/head-turn artefacts unmeasured (keep the IMU).
- **TinyProbe: not relevant.** It is a 32-ch wearable ultrasound probe (FPGA, Wi-Fi 6).
- **BioFoundation / TinyMyo: not now.**
  - TinyMyo is a 3.6M-param sEMG transformer pretrained on 2 kHz, 16-ch forearm data (Ninapro, EMG2Pose). Our data is 500 Hz neck/face silent speech, so it would need resampling and domain transfer for an uncertain gain.
  - It is about 240x SpeechNet's size (3.6M vs 15k params) and was deployed via ARES on GAP9, not ESP32.
  - Its weights are CC BY-ND 4.0, so a fine-tuned derivative could not be redistributed in an open-source device.
  - Worth revisiting only as an offline teacher (distilling into SpeechNet) if cross-day accuracy stays the bottleneck.

Open gaps (empirical, need the bench, not more reading):
1. How much bigram or tiny-neural scoring closes the dictionary-vs-LLM gap in `st-gate` (target: within ~15% of LLM gestures/word).
2. Whether a 1-2 MB int8 scorer meets the flash and latency budget on the S3 (target: under 100 ms per word).
3. Multi-host bonding and iOS/Android/Windows behavior of the HID keyboard on real hardware.

## Prior art on few-input text entry (2026-10-20)
- Tanaka-Ishii, Inutsuka, Takeichi, "Entering Text with A Four-Button Device", COLING 2002 (C02-1149): 4 letter-group buttons, candidates ranked by a PPM language model, adapted with a small user corpus; one user reached 23 wpm. Supports our user-adaptive word list (train on the user's chat and coding text). PPM is a cheap alternative to the neural scorer if needed.
- MacKenzie, "The One-Key Challenge", ASSETS 2009: scanning ambiguous keyboard with one switch, 5.11 wpm average (7.03 error-free), 9.28 wpm for one practiced user. A realistic 5-9 wpm target for very few inputs; also notes the unstable candidate display while typing and that ~95% of English words are unambiguous on a T9 keypad.
