# Utter protocol v1

Implemented by `firmware/src/` (board), `ml/utter/protocol.py` + `ml/utter/fakeboard.py` (host / emulator).

## Ports (UDP)
- 47700: data, board -> host (host listens).
- 47701: control, host -> board. Replies go back to the sender's address.
- 47800: token events, engine/simulator -> Mac app (localhost only).

Discovery: mDNS `utter.local`, service `_utter._udp` port 47701. The host sends `subscribe`; the board streams to that sender. No IP is compiled in.

## Data packet (little-endian header)
| off | type | field |
|---|---|---|
| 0 | u16 | magic 0x4253 |
| 2 | u8 | version = 1 |
| 3 | u8 | nch (16) |
| 4 | u32 | seq (packet counter) |
| 8 | u32 | sample index of first frame |
| 12 | u16 | fs (Hz) |
| 14 | u8 | nframes |
| 15 | u8 | flags: bit0 IMU block present, bit1 test signal, bit2 shorted inputs, bit3 VBUS present |
| 16 | u32 | lead-off P bits (bit i = channel i) |
| 20 | u32 | lead-off N bits |
| 24 | ... | nframes x nch x int24 **big-endian** (raw ADS1298 order) |
| ... | 6 x i16 | IMU ax ay az gx gy gz (if flag bit0) |

Volts = code x 2 x VREF / gain / 2^24, with VREF = 2.4 V. Defaults: fs 2000 (HR mode, -3 dB at 524 Hz; 0.9 uVrms at gain 12 per datasheet Table 1) and gain 12, so 1 LSB = 23.8 nV. nframes = 20.

## Control (one JSON object per UDP datagram, or per line over USB serial at 115200)
- `{"cmd":"info"}` -> `{"ok":true,"fw":"0.1.0","chip_ids":[146,146],"vbat":3.91,"vbus":false,"imu":true,"ip":"..","streaming":false}`
- `{"cmd":"subscribe","port":47700}`
- `{"cmd":"start","fs":2000,"gain":12,"mode":"normal"|"test"|"shorted","leadoff":true}`
- `{"cmd":"stop"}`
- `{"cmd":"wifi","ssid":"..","pass":".."}`: serial only. The board joins the network, stores the credentials in NVS only on success, and replies `{"ok":true,"ip":".."}`.
- `{"cmd":"regs"}`: register dump for both chips (debug).

Safety: `start` is refused with `{"ok":false,"err":"vbus"}` while USB VBUS is present. Streaming stops at once if VBUS appears.

## Token events (to app, JSON over UDP 127.0.0.1:47800)
`{"type":"token","action":"G1".."G4"|"NEXT"|"ACCEPT"|"BACK"|"WAKE","p":0.93,"src":"engine"|"keysim"}`
`{"type":"status","text":"..."}`
