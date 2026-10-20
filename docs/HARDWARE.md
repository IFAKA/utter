# Hardware decision (2026-10-19, DECIDED and designed; not ordered)

User constraints: DIY, Spain (21% IVA, EUR 150 IOSS threshold), cheapest that keeps or improves quality, least friction, max automation. Do not anchor on existing boards; derive from requirements.

## Requirements (silent articulation, lips closed)
- EMG ~5-50 uV; skin-electrode noise ~1-3 uV -> AFE noise <=1 uVrms over 20-500 Hz is enough.
- 1-2 kSPS (EMG energy 20-450 Hz).
- More channels -> cross-day robustness (SilentWear: 77.5% silent, 14 ch, 8 cmds).
- Software-selectable pairing: record monopolar vs common REF, build bipolar pairs digitally; ML ranks channels -> user wears only best sites later.
- Electrode layout: SilentWear's neckband (14 ch, dry textile, 77.5% silent within a day). Ours is in ml/utter/neckband.py: 3 x 4 front grid over the infrahyoid strap muscles + 2 per sternocleidomastoid, REF/RLD at C7, 13 bipolar pairs derived in software. First with gel electrodes at those sites (signal ceiling), then a velcro textile band with dry snap electrodes. Gate for the band: within ~5 points of gel.
- Rest-class artefacts (chew/swallow): cheap external IMU near jaw (ExG+IMU 94%/12 cmds, Whispering Wearables 2024).
- Safety: battery only; firmware blocks acquisition while USB VBUS present.

## Design: "Utter" v1 (designed 2026-10-19, DRC/ERC clean, awaiting independent review + order approval)
Source of truth: hardware/gen/circuit.py. `hardware/gen/build.sh` regenerates the PCB (scripted placement + FreeRouting), schematic, checks (check.py) and JLC files (out/fab/). Order card: docs/ORDER.md.
- 2x TI ADS1298 (LCSC C527440, ~$20 each; ADS1299 ~$55 and overkill for EMG) = 16 ch, 24 bit, 2 kSPS. Shared SPI bus with separate CS (simpler and more robust than daisy chain). U1 is the clock master and the only RLD driver.
- Monopolar inputs: every INxN goes to REF, and bipolar pairs are built digitally. There are no solder jumpers. Each input has 10k + 470 pF C0G. No TVS: the 10k resistors limit current and the board runs on battery only. Fable should review this.
- Power: 3.0 V LP5907 analog LDO behind a ferrite, and a 3.3 V AP2112 digital rail. 1S LiPo on JST-PH through a reverse-polarity P-FET, slide switch, MCP73831 charger (213 mA) and power-path FET. Firmware blocks acquisition while VBUS is present.
- ESP32-S3-WROOM-1-N8 (replaces the MINI from the proposal), at the board edge with an antenna keepout. Native USB-C (USBLC6 ESD) handles flashing and charging.
- 4-pin I2C header for an external IMU (LSM6DS3 module).
- 68 x 46 mm, 4 layers (In1 GND; In2 split AVDD/+3V3), single-sided JLC Economic PCBA, 107 parts, 0.3 mm vias.
- Real cost: ~EUR 190-210 for 2 assembled boards delivered incl. IVA (12 extended-part fees; no basic equivalents that keep quality) + ~EUR 35-45 Amazon.es = ~EUR 225-255. The earlier EUR 185 estimate missed extended fees and IVA above EUR 150.
- Same board serves the Stage 1 proof and the Stage 4 hidden wearable.
- Risks: an unbuilt design with a scripted layout. Independent review (Fable, checklist in ORDER.md) is required before ordering. Reference: TI ADS1298 datasheet and the ADS1298ECG-FE EVM.

## Alternatives evaluated (EUR delivered to Spain, approx.)
| Option | Cost | Verdict |
|---|---|---|
| ../neurodaq via JLC PCBA (2 boards min, 2x ADS1299, double-sided) | ~330 | 8 ch referential EEG montage; firmware pins host IP at compile time; CPL file missing (export from oshwlab project). Schematic has 5V fix (VIN_ESP -> 3V3). |
| ../neurodaq bare PCB + LCSC parts, hand-assembled | ~165-180 | Hard: TQFP-64, WSON exposed pad, both sides. |
| AliExpress OpenBCI Cyton clone (ADS1299, 8 ch) | ~130 | Cheapest ready-made; 250 Hz over RF dongle; clone quality varies; BrainFlow-supported. Fallback. |
| Cerelog ESP-EEG | ~450 | Lowest-risk ready-made fallback. |
| BioAmp EXG Pill x8 | ~270 | TL074, no noise spec; too noisy for lips-closed. |
| ADS131M08 custom | ~100 | ~1.9 uVrms @250 SPS, 1 MOhm input, no RLD -> worse. |
| Chinese ADS1298 clones (LHE7908, AFE948A) | ? | Unverified; skip. |
| Magnetometers (Sonera) | thousands | OPMs + shielded room. |

## Software plan (board-agnostic, unchanged)
Mac menu-bar app (Accessibility typing, 8 tokens, Ollama suggestions, TTS to earbuds); keyboard-as-fake-sensor simulator; Python ML (Gaddy loader, features, rest class, within-session + cross-day eval, channel ranking); firmware; guided recording "game"; setup/flash/acceptance-test wizard (auto chip ID, internal test signal, shorted-input noise, lead-off contact check); order card.

## User's remaining manual steps (product-psychology design, target <=6)
1 order (one card) -> 2 plug battery/leads -> 3 plug USB (auto flash + test) -> 4 stick electrodes until green -> 5 four ~12 min recording sessions -> 6 next-day 3-min check.

## Sources
- SilentWear https://arxiv.org/html/2603.02847 ; EMG neckband https://arxiv.org/abs/2509.21964 ; headphone textile EMG https://arxiv.org/abs/2504.13921
- ADS1298 LCSC https://www.lcsc.com/product-detail/Texas-Instruments_Texas-Instruments-ADS1298IPAGR_C527440.html ; ADS1299 LCSC https://www.lcsc.com/product-detail/Analog-Front-End-AFEs_Texas-Instruments-ADS1299IPAGR_C476817.html
- ADS1298 vs ADS1299 https://openbci.com/forum/index.php?p=%2Fdiscussion%2F121%2Fads1299-vs-ads1298
- JLC PCBA pricing https://jlcpcb.com/help/article/pcb-assembly-price
- Cyton clone build https://github.com/AbhijithSriram/cyton-hardware ; clone issues https://openbci.com/forum/index.php?p=%2Fdiscussion%2F3678%2Fproblems-with-ganglion-cyton-clone-boards
- Cerelog https://www.cerelog.com/eeg_researchers.html ; ADS131M08 EEG https://pmc.ncbi.nlm.nih.gov/articles/PMC11647867/
- BioAmp https://www.circuitstate.com/tutorials/upside-down-labs-bioamp-exg-pill-v0-7-biopotential-afe-hardware-overview-and-interfacing-with-arduino/
- Sonera https://www.biorxiv.org/content/10.1101/2025.08.04.668236v1 ; AlterEgo https://andymatuschak.org/files/papers/Kapur%20et%20al%20-%202018%20-%20AlterEgo.pdf
- Chinese ADS1298 alternatives https://www.eefocus.com/article/1608604.html
