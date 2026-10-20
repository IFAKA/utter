# Using Utter

One-time host setup (already done on this Mac): `uv`, PlatformIO (`pio`), Ollama with `ollama pull gemma3:1b` (and `ollama pull all-minilm` so remembered replies match reworded agent messages), Xcode command line tools. Then:

```sh
cd ml && uv sync            # host tools; `uv run utter --help` lists every command
cd app && swift build -c release
```

## Your 6 steps
1. **Order** the boards with the card in docs/ORDER.md, plus the Amazon.es items listed there.
2. **Plug** the LiPo into J4 and the electrode leads into J1. J1 pins 1-16 are EL1-16, 17/18 are REF and 19/20 are RLD; pin 1 is marked on the silkscreen. Plug the optional IMU into J2.
3. **Plug in USB-C** and run `uv run utter setup`. It flashes the firmware, checks that both ADS1298 chips answer, copies the Mac's Wi-Fi to the board, asks you to unplug USB, then runs the acceptance test (internal test signal and shorted-input noise). The board refuses to record while USB is plugged in.
4. **Put on the dry band** (everyday; see docs/HARDWARE.md "Everyday band"): the mark sits under the Adam's apple, close the velcro snugly. Gel electrodes are only for the one-time signal-ceiling test, in the neckband layout (`ml/utter/neckband.py`, after SilentWear): a 3 x 4 grid on the front of the neck starting just below the larynx (columns 1 and 3 cm either side of the midline, rows 2 cm apart, EL1-12), two electrodes along each side muscle (EL13-16), REF and RLD side by side at the back of the neck. Run `uv run utter electrodes`; it names each site, so press each one until it shows green.
5. **Record 4 sessions** of about 12 minutes with `uv run utter record`. A game prompts each silent token and the rest class. Then run `uv run utter train` (add `--rank 8` to find the best electrode sites).
6. **Next day**, do a 3-minute check: `uv run utter record --minutes 3`, then `uv run utter train`. The cross-day accuracy is the Stage 2 gate (>80%).

## Typing
- Start the app with `app/.build/release/Utter` (a menu-bar icon). Grant Accessibility permission when asked. `--dry-run` shows the text without typing it.
- Live input: `uv run utter engine` sends recognised tokens to the app over UDP 127.0.0.1:47800.
- Without hardware: `uv run utter keysim --accuracy 0.8` uses the keyboard as a fake sensor with injected errors. `uv run utter fakeboard`, or `--fake` on any command, emulates the board.
- Gates: `swift run st-gate` (Stage 0 typing gate) and `uv run utter gaddy` (real-EMG benchmark, see ml/README.md).

## Simulation (no hardware)
See the whole product run live on the board emulator (synthetic EMG; a plumbing demo, not evidence real EMG works):
1. Signals: `uv run utter scope --fake` opens a live 16-channel view; the emulator articulates a random token every 2.5 s.
2. Train on synthetic sessions: `uv run utter synth`, then `uv run utter train`.
3. App: `app/.build/release/Utter --dry-run` (menu-bar; shows text without typing).
4. Recognizer: `uv run utter engine --fake`. Type a token name (e.g. `kee`) + Enter to "articulate" it; the engine recognizes it and the app turns it into suggestions/text.
With the real board, drop `--fake` (`utter scope` is also the live view for electrode checks).


## Utter with Claude Code
Two hooks connect Claude Code to the Utter app. They are already on in this repo (`.claude/settings.json`).
- When the agent finishes, the earbud reads the first sentence of its reply plus the top suggestion, and predictions use the reply as context. In the benchmark this cuts gestures per word by 39%.
- When the agent asks permission, do your **ACCEPT** command to allow (Return) or **BACK** to deny (Escape). The menu bar shows `allow? accept / back`.

To use it in every project, add the same `hooks` block to `~/.claude/settings.json`, with the script's absolute path:
`python3 /Users/faka/code/projects/hardware/health/utter/app/hooks/utter_hook.py`.
If the Utter app isn't running, the hook silently does nothing.
