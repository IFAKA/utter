# Handoff for a new chat
Goal: covert "silent typing" input method (no keyboard, no voice). Lips closed, internal articulation; sEMG on chin/throat/behind ear.
Hardware: ADS1299 + ESP32-S3 neckband, ~EUR 175 (Spain, IVA incl.). Reference build in ../neurodaq (read-only; its submodules not yet fetched).
Software: ~8 silent tokens + local LLM next-word suggestions + earbud voice; Mac app first.
User priority: prove it works before optimizing; speed is secondary. Follow gates in PLAN.md.
Next step: Stage 0 - build keyboard-as-fake-sensor simulator in app/ (measure tokens/sentence at 80%/90% accuracy); optionally download Gaddy dataset into ml/data (gitignored).
Model guidance: Sonnet for software; Fable for schematic/PCB review before ordering, safety, and Stage 2 failure analysis.
