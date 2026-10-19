// Two ADS1298 on one SPI bus with separate chip selects (not daisy-chained).
#pragma once
#include <Arduino.h>
#include <SPI.h>

namespace ads {
enum Reg : uint8_t {
  ID = 0x00, CONFIG1, CONFIG2, CONFIG3, LOFF, CH1SET, RLD_SENSP = 0x0D, RLD_SENSN, LOFF_SENSP,
  LOFF_SENSN, LOFF_FLIP, LOFF_STATP, LOFF_STATN, GPIO, PACE, RESP, CONFIG4, WCT1, WCT2, NREGS
};
enum Mode : uint8_t { NORMAL = 0, SHORTED = 1, TEST = 5 };  // CHnSET MUX codes
constexpr int NCHIP = 2, NCH = 16, FRAME = 27;              // bytes per chip per sample: 3 status + 8 x 3

void begin();                         // power-up, reset, master clock out, both chips idle (SDATAC)
uint8_t readReg(int chip, uint8_t reg);
void writeReg(int chip, uint8_t reg, uint8_t val);
bool configure(int fs, int gain, Mode mode, bool leadoff);  // false if fs/gain unsupported
void startStream();                   // RDATAC on both, START high
void stopStream();                    // START low, SDATAC
void readFrame(uint8_t* out);         // NCHIP x FRAME bytes, call after DRDY1 falls
}  // namespace ads
