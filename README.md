# silent-typing

Covert text input: silently articulate (lips closed, no sound) and text appears in any app.
Surface EMG (chin/throat/behind ear) -> ADS1299 + ESP32-S3 -> ~8 silent tokens -> local LLM suggestions -> earbud feedback -> typed text.

**Not a medical device.** Battery-powered / isolated operation only.

Reference (read-only, MIT): ../neurodaq (carlos-lorenzo/neurodaq) for ADS1299 driver and board design. Credit it wherever code is reused.

See docs/PLAN.md for stages and pass/fail gates.
