// Utter pin map (ESP32-S3-MINI-1). The schematic generator reads this file:
// keep one "#define PIN_<NAME> <gpio>" per line. Avoids strapping pins (0, 3, 45, 46) and USB (19, 20).
#pragma once
#define PIN_SCLK 12   // ADS1298 SCLK (both chips)
#define PIN_MOSI 11   // ADS1298 DIN (both)
#define PIN_MISO 13   // ADS1298 DOUT (both, tri-stated when CS is high)
#define PIN_CS1 10    // master ADS1298 (CLKSEL=1, CLK_EN: drives CLK of the slave), channels 1-8
#define PIN_CS2 9     // slave ADS1298 (CLKSEL=0), channels 9-16
#define PIN_DRDY1 8   // master DRDY (both chips convert in lockstep: shared CLK and START)
#define PIN_DRDY2 7   // slave DRDY (sync check)
#define PIN_START 6   // shared START
#define PIN_RESET 5   // shared RESET (active low)
#define PIN_PWDN 4    // shared PWDN (active low)
#define PIN_VBUS 14   // USB VBUS sense via 100k/100k divider: high = USB present -> no acquisition
#define PIN_VBAT 1    // battery via 100k/100k divider (ADC1)
#define PIN_SDA 15    // IMU connector (LSM6DS3 module)
#define PIN_SCL 16
#define PIN_LED 21    // status LED (active high)
