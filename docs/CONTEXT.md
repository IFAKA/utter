# Handoff for a new chat
Goal: Utter, an open-source, non-invasive silent-speech input method (no keyboard, no voice), aimed at people losing their voice (ALS). Lips closed, internal articulation; 16 sEMG channels on a dry fabric neckband.
Software: ~8 silent tokens + next-word suggestions (offline LSTM, or a local LLM that reads the agent's message) + reply memory + earbud voice; Mac app first.
User priority: prove it works before optimizing; speed is secondary. Follow gates in PLAN.md.

## State (2026-10-20)
- Hardware: Utter v1 designed (2x ADS1298 = 16 ch, ESP32-S3-WROOM-1, 68x46 mm, 4 layers, JLC PCBA). `hardware/gen/build.sh` regenerates everything and fails unless DRC 0/0, ERC clean (with documented waivers), and circuit == schematic == PCB. Fab files are in hardware/out/fab/. NOT ORDERED. Cost ~EUR 225-255 all-in. Details: docs/HARDWARE.md, docs/ORDER.md.
- Electrode layout (`ml/utter/neckband.py`): EL1-12 a 3x4 front-neck grid (columns ±1/±3 cm, rows 2 cm apart, top row just below the larynx), EL13-16 two per sternocleidomastoid, REF/RLD at C7.
- Everyday band (HARDWARE.md "Everyday band"): fabric velcro neckband (after SilentWear) with reusable Datwyler SoftPulse dry electrodes on snaps. Gel electrodes only for the one-time signal-ceiling test. Gap: ORDER.md still lists only gel electrodes, not the band or the dry electrodes.
- Recognition (PLAN.md): SpeechNet classifier with cross-day recovery (norm + augmentation + AdaBN + online learning). Adaptive window: 1.4 s each morning, 0.8 s once online learning has caught up. Simulated with real recognizer errors: ~4 wpm on a fresh morning, ~7.5 wpm after learning with the LLM reading the agent's message.
- Prediction: the app ships the chat + coding LSTM (1.4 MB, `NeuralPredictor.bundled()`), used when Ollama is absent; with Ollama, gemma3:1b with context. Reply memory (`ReplyMemory.swift`) offers past replies, matched by word overlap or all-minilm embeddings; halves the work on reworded questions in simulation.
- Software done: firmware (PlatformIO, builds), `utter` host tools (ml/), Mac app (swift build OK; st-gate PASS = Stage 0 gate), setup wizard, guided recording, spell mode. See docs/USAGE.md.
- Demo site: `docs/demo.html` (neckband 3D model, kit viewer, Try-it with the same offline LSTM and reply memory in the browser, no 137 MB model). Deployed to https://utter-nine.vercel.app (Vercel project "utter"; deploy a staging copy with demo.html as index.html plus docs/assets/).
- User wants: DIY, in Spain, cheapest that keeps/improves quality, design from requirements, user's manual part <=6 steps with a guided UI.

## Next step
1. Add the fabric band and SoftPulse dry electrodes to ORDER.md.
2. User places the JLC order (ORDER.md) and buys the Amazon.es items.
3. After delivery: USAGE.md steps 2-6, the gel-vs-dry signal test, then the Stage 1 gate.
4. Real daily use decides how much reply memory and the adaptive window are worth.

Model guidance: Sonnet for software; Fable for schematic/PCB review before ordering, safety, and Stage 2 failure analysis.
Never place orders or spend money; user approves the order card.
