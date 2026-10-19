# Order card: SilentBand v1 (APPROVED 2026-10-19, user places the order)

Status 2026-10-19: machine-checked, Fable-reviewed (no blockers), approved by the user. Nobody places this order except the user.

Regenerate everything with `hardware/gen/build.sh` (~1.5 min). It fails unless DRC is 0 errors with 0 unconnected, ERC is clean apart from the waivers listed below, and circuit.py, the schematic and the PCB have identical nets.

## Files (hardware/out/fab/)
| File | Use |
|---|---|
| silentband-gerbers.zip | JLCPCB "Add gerber file" |
| silentband-bom.csv | PCBA step: BOM (LCSC part numbers) |
| silentband-cpl.csv | PCBA step: CPL (placement) |
| silentband-schematic.pdf, silentband-top-assembly.pdf, render-top/bottom.png | review only |

## JLCPCB settings
- PCB: 4 layers, 68 x 46 mm, 1.6 mm FR-4, qty 5, green mask, lead-free HASL. Everything else stays at the defaults.
- Rules used: track/space ≥ 0.1 mm, vias 0.5-0.6 mm with a 0.3 mm drill. These are standard 4-layer capabilities with no small-via surcharge.
- PCBA: Economic, top side only, assemble **2** of the 5 boards, tick "Confirm parts placement" (free). A JLC engineer sends a placement preview. Check that the pin-1 dots of U1, U2, U4-U7, Q1, Q2 and the polarity marks of D1-D3 and the tantalum caps C20, C32 (+ to VCAP1) match the silkscreen. This is the only placement check; KiCad-vs-JLC rotation offsets are fixed there.
- If Economic is not offered for 4 layers on the day, Standard PCBA adds about $25 setup.

## Cost estimate (2 assembled boards, JLC prices checked 2026-10-19 with `hardware/gen/jlc.py`)
| Item | USD |
|---|---|
| Parts, 2 boards (2x ADS1298 ≈ $40 per board, ESP32-S3-WROOM-1 ≈ $5, rest ≈ $3) | ~96 |
| 5 bare 4-layer PCBs | ~10-15 |
| PCBA setup + stencil + joints | ~11 |
| Extended-part fees: 13 unique types x $3 | 39 |
| Shipping to Spain (Global Standard) | ~15-20 |
| **Subtotal** | **~170-180 (≈ EUR 155-165)** |
| IVA 21%: above EUR 150 the courier collects it, plus a handling fee (~EUR 10-15) | ~EUR 35-45 |
| **Boards delivered** | **≈ EUR 190-210** |

None of the 13 extended parts had a basic or preferred-extended equivalent that keeps the quality (searched 2026-10-19). Two near-misses:
- The 470 pF input-filter caps stay C0G: X7R is piezoelectric and would add motion artifacts on electrode inputs.
- The 3.3 V LDO must supply ~355 mA Wi-Fi peaks from a LiPo, which rules out XC6206 and AMS1117.

## Amazon.es (≈ EUR 35-45)
- 1S LiPo, 3.7 V, 500-1000 mAh, with protection circuit and **JST-PH 2.0** plug. Polarity does not matter for safety: Q1 blocks a reversed cell, and the board then just won't power on. If that happens, swap the two crimps.
- Ag/AgCl pre-gelled snap electrodes (pack of 50+) and snap lead wires ending in 2.54 mm Dupont female sockets (10+ leads).
- Optional IMU: GY-LSM6DS3 breakout plus 4 Dupont wires. J2 pin order is 3V3, GND, SDA, SCL (pin 1 is marked).

## Independent review checklist (Fable)
1. ADS1298 x2 on a shared SPI bus with separate CS. U1 is the clock master (CLKSEL=1, CLK_EN) and drives U2's CLK through 33 Ω. U2 has CLKSEL=0. START, RESET and PWDN are shared. Check against datasheet sections 9.5 and 10.1.
2. Unipolar 3.0 V AVDD (LP5907) with AVSS=GND, internal reference, and VCAP/VREF decoupling values (circuit.py `ads()`).
3. Inputs: 10k + 470 pF C0G per input; all INxN go to REF. RLD comes from U1 only: RLDOUT → 10k → electrode, with 1M ∥ 2.2 nF feedback. There is no TVS on the electrode lines; the 10k series resistors limit current. Is that adequate for a battery-only wearable?
4. Unused pins:
   - TESTP/TESTN and RLDIN tied to AVDD.
   - GPIO1-4 tied to GND. Firmware writes GPIO=0x0F (inputs); a firmware bug could drive them into GND.
   - The rest are no-connect.
5. Power:
   - Q1 reverse-polarity guard.
   - Slide switch, then Q2 load-sharing (gate = VBUS, 100k pull-down), with a B5819W from VBUS to VSYS.
   - MCP73831 charging at 213 mA.
   - Ferrite into the analog LDO.
   - VBUS sense: firmware refuses acquisition while USB is present.
6. Layout:
   - In1 is solid GND.
   - In2 is AVDD under the analog half, +3V3 under the digital half, with a +3V3 notch under each ADS digital corner (DVDD pins). B.Cu references In2, not In1: clock nets (CLK_M, CLK_S, SCLK) are therefore forced onto F.Cu over solid In1 GND. MOSI/MISO/CS/START/PWDN/RESET still partly run on B.Cu over the analog half and cross the split; firmware sets the weakest GPIO drive to slow their edges. Acceptable?
   - Antenna keepout on all layers.
   - USB-C and JST at the bottom edge.
7. ERC waivers: both DOUT pins on MISO (tri-state while CS is high), the GPIO and TESTP ties, and footprint-only GND pads (switch shell, JST tabs).

## Fable review (2026-10-19): no blockers
Fixed:
- Slave reset now waits 150 ms after the master enables CLK (tPOR starts at valid CLK, datasheet 11.1).
- VCAP1: 22 uF X5R (microphonic on a jaw-worn board) -> 22 uF tantalum C7183 (datasheet 11).
- Clock nets kept on F.Cu over solid GND; slow-edge drive on SPI/control GPIOs.
- Firmware refuses to start below 3.55 V and stops below 3.50 V (AP2112 dropout + Wi-Fi peaks).
Accepted for v1 (revisit in v2): no TVS on electrode lines (ADS1298 2 kV HBM; add low-C TVS arrays), WCT pin floating (WCT amps off), MCP73831 thermal throttling, J1 SMD header (THT if it wears), lower-dropout 3.3 V LDO.

