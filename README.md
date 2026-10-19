# Utter

Covert text input: silently articulate (lips closed, no sound) and text appears in any app.
Surface EMG (chin/throat/behind ear) -> Utter (2x ADS1298 = 16 ch + ESP32-S3) -> ~8 silent tokens -> local LLM suggestions -> earbud feedback -> typed text.

**Not a medical device.** Battery-powered operation only; the firmware refuses to record while USB is connected.

- docs/PLAN.md: stages and pass/fail gates
- docs/USAGE.md: setup and the user's 6 steps
- docs/HARDWARE.md, docs/ORDER.md: board design and order card
- Layout: hardware/ (generated KiCad board, `hardware/gen/build.sh`), firmware/ (PlatformIO), ml/ (`utter` host tools), app/ (Mac menu-bar app)

## Third-party data
- app/Sources/TypingCore/Resources/words_{en,es}.txt are derived from wordfreq (https://github.com/rspeer/wordfreq) word lists, CC-BY-SA 4.0. The derived lists keep that license.
- The Gaddy & Klein silent-speech EMG dataset (https://zenodo.org/records/4064409), CC-BY-4.0, is downloaded locally and not redistributed.
