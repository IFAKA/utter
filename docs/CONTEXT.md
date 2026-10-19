# Handoff for a new chat
Goal: Utter, a covert silent-speech input method (no keyboard, no voice). Lips closed, internal articulation; sEMG on chin/throat/behind ear.
Software: ~8 silent tokens + local LLM next-word suggestions + earbud voice; Mac app first.
User priority: prove it works before optimizing; speed is secondary. Follow gates in PLAN.md.

## State (2026-10-19)
- Hardware: Utter v1 designed (2x ADS1298 = 16 ch, ESP32-S3-WROOM-1, 68x46 mm, 4 layers, JLC PCBA). `hardware/gen/build.sh` regenerates everything and fails unless DRC 0/0, ERC clean (with documented waivers), and circuit == schematic == PCB. Fab files are in hardware/out/fab/. NOT ORDERED. Cost ~EUR 225-255 all-in. Details: docs/HARDWARE.md, docs/ORDER.md.
- Software done: firmware (PlatformIO, builds), `utter` host tools (ml/, 3 tests pass), Mac app (swift build OK; st-gate PASS = Stage 0 gate), setup wizard, guided recording. See docs/USAGE.md.
- User wants: DIY, in Spain, cheapest that keeps/improves quality, design from requirements, user's manual part <=6 steps with a guided UI.

## Next step
1. Done 2026-10-19: Fable review, no blockers, fixes applied (ORDER.md "Fable review").
2. Approved 2026-10-19. User places the JLC order (ORDER.md) and buys the Amazon.es items.
3. After delivery: USAGE.md steps 2-6, then the Stage 1 gate.

Model guidance: Sonnet for software; Fable for schematic/PCB review before ordering, safety, and Stage 2 failure analysis.
Never place orders or spend money; user approves the order card.
