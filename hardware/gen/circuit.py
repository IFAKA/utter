"""Utter circuit: the single source of truth for schematic, PCB and BOM.

Each part: reference, KiCad symbol, KiCad footprint, value, LCSC code, {pad: net}, placement group.
Pad numbers equal symbol pin numbers for every symbol used here (checked by gen_sch.py).
GPIO assignments are read from firmware/src/pins.h so firmware and board cannot drift apart.

Design notes (for the reviewer):
- 2x ADS1298 on one SPI bus with separate CS (not daisy chain). U1 is the clock master: CLKSEL=1,
  CONFIG1.CLK_EN=1, its CLK pin drives U2's CLK (CLKSEL=0) through 33R. START/RESET/PWDN shared.
- Unipolar supply: AVDD = 3.0 V (LP5907, 6.5 uVrms), AVSS = GND, internal 2.4 V reference.
  DVDD = 3.3 V digital rail (shared with the ESP32-S3). Single solid ground plane (In1).
- 16 monopolar channels: INxP = electrode x through 10k + 470p C0G to GND; all INxN = REF electrode
  through one 10k + 470p. Bipolar pairs are formed in software. Right-leg drive from U1 only
  (RLDOUT -> 10k -> RLD electrode; 1M || 2.2n feedback to RLDINV). 10k series limits fault current.
- Power: 1S LiPo (JST-PH, protected cell) -> reverse-polarity P-FET (Q1) -> slide switch -> P-FET load sharing with USB (Schottky);
  MCP73831 charger (~210 mA). USB VBUS also goes to a GPIO divider: firmware blocks acquisition
  while USB is attached (battery-only recording).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


@dataclass
class Part:
    ref: str
    symbol: str
    footprint: str
    value: str
    lcsc: str
    pads: dict[str, str]
    group: str
    dnp: bool = False
    fields: dict = field(default_factory=dict)


def gpio_map() -> dict[str, int]:
    text = (REPO / "firmware/src/pins.h").read_text()
    return {m[0]: int(m[1]) for m in re.findall(r"#define PIN_(\w+) (\d+)", text)}


# LCSC parts (verified with jlc.py: stock, basic/extended)
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
LCSC_R = {"10k": "C25744", "100k": "C25741", "1M": "C26083", "4.7k": "C25900", "5.1k": "C25905",
          "1k": "C11702", "33": "C25105"}
LCSC_C = {"100n": ("C1525", C0402), "470p C0G": ("C75274", C0402), "2.2n": ("C1604", C0603),
          "1u": ("C15849", C0603), "10u": ("C19702", C0603)}

parts: list[Part] = []
_n: dict[str, int] = {}


def ref(prefix: str) -> str:
    _n[prefix] = _n.get(prefix, 0) + 1
    return f"{prefix}{_n[prefix]}"


def add(prefix, symbol, footprint, value, lcsc, pads, group, **kw) -> Part:
    p = Part(ref(prefix), symbol, footprint, value, lcsc, {str(k): v for k, v in pads.items()}, group, **kw)
    parts.append(p)
    return p


def R(value, a, b, group):
    return add("R", "Device:R_Small", R0402, value, LCSC_R[value], {1: a, 2: b}, group)


def C(value, a, b, group):
    lcsc, fp = LCSC_C[value]
    return add("C", "Device:C_Small", fp, value, lcsc, {1: a, 2: b}, group)


def build() -> list[Part]:
    parts.clear(); _n.clear()
    io = gpio_map()

    # ---------------- electrode connector + input filters ----------------
    j1 = {i: f"EL{i}" for i in range(1, 17)}
    j1.update({17: "REF_E", 18: "REF_E", 19: "RLD_E", 20: "RLD_E"})
    add("J", "Connector_Generic:Conn_02x10_Odd_Even", "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical_SMD",
        "Electrodes", "C42372532", j1, "conn")
    for i in range(1, 17):
        g = "afe1" if i <= 8 else "afe2"
        R("10k", f"EL{i}", f"IN{i}", g)
        C("470p C0G", f"IN{i}", "GND", g)
    R("10k", "REF_E", "REF", "afe1")
    C("470p C0G", "REF", "GND", "afe1")

    # ---------------- ADS1298 x2 ----------------
    for chip in (1, 2):
        master = chip == 1
        g = f"ads{chip}"
        pads = {}
        for ch in range(8):  # IN1N..IN8N = pads 15,13,..,1 ; IN1P..IN8P = 16,14,..,2
            pads[15 - 2 * ch] = "REF"
            pads[16 - 2 * ch] = f"IN{ch + 1 + (0 if master else 8)}"
        for p in (17, 18, 62):                # TESTP/TESTN, RLDIN unused -> AVDD (datasheet note 1)
            pads[p] = "AVDD"
        for p in (19, 21, 22, 54, 56, 59):
            pads[p] = "AVDD"
        for p in (20, 23, 25, 32, 53, 57, 58, 33, 49, 51, 31, 41, 42, 44, 45, 46):
            pads[p] = "GND"                   # AVSS, VREFN, DGND, RESV1, DAISY_IN, GPIO1-4
        for p in (48, 50):
            pads[p] = "+3V3"
        pads.update({24: f"VREFP{chip}", 26: f"VCAP4_{chip}", 28: f"VCAP1_{chip}", 30: f"VCAP2_{chip}",
                     55: f"VCAP3_{chip}", 34: "MOSI", 43: "MISO", 40: "SCLK", 39: f"CS{chip}", 35: "PWDN",
                     36: "RESET", 38: "START", 47: f"DRDY{chip}", 37: "CLK_M" if master else "CLK_S",
                     52: "+3V3" if master else "GND"})
        for p in (27, 29, 60, 64):            # NC, NC, RLDREF (internal, RLDREF_INT=1), WCT: no connect
            pads[p] = ""
        pads.update({61: "RLDINV", 63: "RLDOUT"} if master else {61: "", 63: ""})
        add("U", "Analog_ADC:ADS1298xPAG", "Package_QFP:TQFP-64_10x10mm_P0.5mm", "ADS1298IPAGR", "C527440", pads, g)
        C("10u", f"VREFP{chip}", "GND", g)
        C("100n", f"VREFP{chip}", "GND", g)
        # VCAP1: tantalum, not X5R: the board is worn on the jaw and class-2 ceramics are microphonic (datasheet 11)
        add("C", "Device:C_Polarized_Small", "Capacitor_Tantalum_SMD:CP_EIA-3216-18_Kemet-A", "22u", "C7183",
            {1: f"VCAP1_{chip}", 2: "GND"}, g)
        for v in ("VCAP2", "VCAP3", "VCAP4"):
            C("1u", f"{v}_{chip}", "GND", g)
        C("1u", "AVDD", "GND", g)
        for _ in range(3):
            C("100n", "AVDD", "GND", g)
        C("1u", "+3V3", "GND", g)
        C("100n", "+3V3", "GND", g)
    R("33", "CLK_M", "CLK_S", "ads2")
    R("1M", "RLDOUT", "RLDINV", "ads1")
    C("2.2n", "RLDOUT", "RLDINV", "ads1")
    R("10k", "RLDOUT", "RLD_E", "afe1")

    # ---------------- ESP32-S3 ----------------
    esp_pad = {"IO0": 27, "IO1": 39, "IO2": 38, "IO3": 15, "IO4": 4, "IO5": 5, "IO6": 6, "IO7": 7, "IO8": 12,
               "IO9": 17, "IO10": 18, "IO11": 19, "IO12": 20, "IO13": 21, "IO14": 22, "IO15": 8, "IO16": 9,
               "IO17": 10, "IO18": 11, "IO21": 23}
    net_of = {"SCLK": "SCLK", "MOSI": "MOSI", "MISO": "MISO", "CS1": "CS1", "CS2": "CS2", "DRDY1": "DRDY1",
              "DRDY2": "DRDY2", "START": "START", "RESET": "RESET", "PWDN": "PWDN", "VBUS": "VBUS_SENSE",
              "VBAT": "VBAT_SENSE", "SDA": "SDA", "SCL": "SCL", "LED": "LED"}
    esp = {i: "" for i in range(1, 42)}  # unused GPIOs: no connect
    esp.update({1: "GND", 40: "GND", 41: "GND", 2: "+3V3", 3: "EN", 27: "BOOT", 13: "USB_DN", 14: "USB_DP"})
    for name, gpio in io.items():
        esp[esp_pad[f"IO{gpio}"]] = net_of[name]
    add("U", "RF_Module:ESP32-S3-WROOM-1", "RF_Module:ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1-N8", "C2913198", esp, "mcu")
    C("10u", "+3V3", "GND", "mcu")
    C("100n", "+3V3", "GND", "mcu")
    R("10k", "+3V3", "EN", "mcu")
    C("1u", "EN", "GND", "mcu")
    R("10k", "+3V3", "BOOT", "mcu")
    add("SW", "Switch:SW_Push", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "RESET", "C318884",
        {1: "EN", 2: "GND"}, "mcu")
    add("SW", "Switch:SW_Push", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "BOOT", "C318884",
        {1: "BOOT", 2: "GND"}, "mcu")
    R("1k", "LED", "LED_A", "mcu")
    add("D", "Device:LED_Small", "LED_SMD:LED_0603_1608Metric", "red", "C2286", {1: "GND", 2: "LED_A"}, "mcu")

    # IMU connector (LSM6DS3 breakout): 3V3, GND, SDA, SCL
    add("J", "Connector_Generic:Conn_01x04", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical_SMD_Pin1Left",
        "IMU", "C46061677", {1: "+3V3", 2: "GND", 3: "SDA", 4: "SCL"}, "imu")
    R("4.7k", "+3V3", "SDA", "imu")
    R("4.7k", "+3V3", "SCL", "imu")

    # ---------------- USB-C ----------------
    usb = {p: "VBUS" for p in ("A4", "A9", "B4", "B9")}
    usb.update({p: "GND" for p in ("A1", "A12", "B1", "B12", "SH")})
    usb.update({"A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DN", "B7": "USB_DN", "A8": "", "B8": ""})
    add("J", "Connector:USB_C_Receptacle_USB2.0_16P", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
        "USB-C", "C165948", usb, "usb")
    R("5.1k", "CC1", "GND", "usb")
    R("5.1k", "CC2", "GND", "usb")
    add("U", "Power_Protection:USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", "USBLC6-2SC6", "C7519",
        {1: "USB_DP", 6: "USB_DP", 3: "USB_DN", 4: "USB_DN", 2: "GND", 5: "VBUS"}, "usb")
    R("100k", "VBUS", "VBUS_SENSE", "usb")
    R("100k", "VBUS_SENSE", "GND", "usb")

    # ---------------- battery, charger, power path ----------------
    add("J", "Connector_Generic:Conn_01x02", "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
        "LiPo 1S", "C295747", {1: "BAT_IN", 2: "GND", "MP": "GND"}, "power")
    add("Q", "Transistor_FET:AO3401A", "Package_TO_SOT_SMD:SOT-23", "AO3401A", "C15127",
        {1: "GND", 2: "VBAT", 3: "BAT_IN"}, "power")   # reverse-polarity guard: off if the cell is plugged reversed
    add("U", "Battery_Management:MCP73831-2-OT", "Package_TO_SOT_SMD:SOT-23-5", "MCP73831T-2ACI/OT", "C424093",
        {1: "CHG_STAT", 2: "GND", 3: "VBAT", 4: "VBUS", 5: "PROG"}, "power")
    R("4.7k", "PROG", "GND", "power")              # 1000 V / 4.7k = ~213 mA charge current
    C("10u", "VBUS", "GND", "power")
    C("10u", "VBAT", "GND", "power")
    R("1k", "VBUS", "CHG_A", "power")
    add("D", "Device:LED_Small", "LED_SMD:LED_0603_1608Metric", "red", "C2286", {1: "CHG_STAT", 2: "CHG_A"}, "power")
    add("SW", "Switch:SW_SPDT", "Button_Switch_SMD:SW_SPDT_Shouhan_MSK12C02", "POWER", "C431540",
        {1: "VBAT_SW", 2: "VBAT", 3: "NC_SW", "SH": "GND"}, "power")
    add("Q", "Transistor_FET:AO3401A", "Package_TO_SOT_SMD:SOT-23", "AO3401A", "C15127",
        {1: "VBUS", 2: "VSYS", 3: "VBAT_SW"}, "power")   # off while USB present; body diode VBAT->VSYS
    R("100k", "VBUS", "GND", "power")                 # gate pull-down when USB absent
    add("D", "Device:D_Schottky_Small", "Diode_SMD:D_SOD-123", "B5819W", "C8598", {1: "VSYS", 2: "VBUS"}, "power")
    C("10u", "VSYS", "GND", "power")
    R("100k", "VBAT_SW", "VBAT_SENSE", "power")
    R("100k", "VBAT_SENSE", "GND", "power")
    C("100n", "VBAT_SENSE", "GND", "power")
    add("U", "Regulator_Linear:AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", "AP2112K-3.3TRG1", "C51118",
        {1: "VSYS", 2: "GND", 3: "VSYS", 4: "NC_LDO1", 5: "+3V3"}, "power")
    C("10u", "+3V3", "GND", "power")
    add("FB", "Device:FerriteBead_Small", "Inductor_SMD:L_0603_1608Metric", "600R@100MHz", "C1002",
        {1: "VSYS", 2: "VSYS_A"}, "aldo")   # analog LDO group sits on the AVDD plane, between the ADCs
    add("U", "Regulator_Linear:LP5907MFX-3.0", "Package_TO_SOT_SMD:SOT-23-5", "LP5907MFX-3.0/NOPB", "C475492",
        {1: "VSYS_A", 2: "GND", 3: "VSYS_A", 4: "NC_LDO2", 5: "AVDD"}, "aldo")
    C("1u", "VSYS_A", "GND", "aldo")
    C("1u", "AVDD", "GND", "aldo")
    C("10u", "AVDD", "GND", "aldo")
    return list(parts)


def nets(ps: list[Part]) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list] = {}
    for p in ps:
        for pad, n in p.pads.items():
            if n:
                out.setdefault(n, []).append((p.ref, pad))
    return out


if __name__ == "__main__":
    ps = build()
    ns = nets(ps)
    print(f"{len(ps)} parts, {len(ns)} nets")
    for n, conns in sorted(ns.items()):
        if len(conns) < 2 and not n.startswith("NC"):
            print("single-pin net:", n, conns)
