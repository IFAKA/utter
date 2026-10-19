#include "ads1298.h"
#include "pins.h"

namespace ads {
static SPIClass spi(FSPI);
static const SPISettings cfg(8000000, MSBFIRST, SPI_MODE1);
static const int cs[NCHIP] = {PIN_CS1, PIN_CS2};
// fCLK = 2.048 MHz: multi-byte commands need 4 tCLK (~2 us) between bytes.
static inline void tdecode() { delayMicroseconds(3); }

enum Op : uint8_t { WAKEUP = 0x02, RESET = 0x06, RDATAC = 0x10, SDATAC = 0x11, RREG = 0x20, WREG = 0x40 };

static void op(int chip, uint8_t c) {
  spi.beginTransaction(cfg);
  digitalWrite(cs[chip], LOW);
  spi.transfer(c);
  tdecode();
  digitalWrite(cs[chip], HIGH);
  spi.endTransaction();
}

uint8_t readReg(int chip, uint8_t reg) {
  spi.beginTransaction(cfg);
  digitalWrite(cs[chip], LOW);
  spi.transfer(RREG | reg); tdecode();
  spi.transfer(0); tdecode();
  uint8_t v = spi.transfer(0); tdecode();
  digitalWrite(cs[chip], HIGH);
  spi.endTransaction();
  return v;
}

void writeReg(int chip, uint8_t reg, uint8_t val) {
  spi.beginTransaction(cfg);
  digitalWrite(cs[chip], LOW);
  spi.transfer(WREG | reg); tdecode();
  spi.transfer(0); tdecode();
  spi.transfer(val); tdecode();
  digitalWrite(cs[chip], HIGH);
  spi.endTransaction();
}

// HR-mode DR codes; CONFIG1 = HR | DAISY_EN (multiple readback) | CLK_EN (master only) | DR.
static int drCode(int fs) {
  switch (fs) {
    case 500: return 6; case 1000: return 5; case 2000: return 4; case 4000: return 3;
    default: return -1;
  }
}
static int gainCode(int g) {
  switch (g) {
    case 6: return 0; case 1: return 1; case 2: return 2; case 3: return 3;
    case 4: return 4; case 8: return 5; case 12: return 6; default: return -1;
  }
}

void begin() {
  for (int c : cs) { pinMode(c, OUTPUT); digitalWrite(c, HIGH); }
  pinMode(PIN_START, OUTPUT); digitalWrite(PIN_START, LOW);
  pinMode(PIN_RESET, OUTPUT); digitalWrite(PIN_RESET, HIGH);
  pinMode(PIN_PWDN, OUTPUT); digitalWrite(PIN_PWDN, HIGH);
  pinMode(PIN_DRDY1, INPUT_PULLUP);
  pinMode(PIN_DRDY2, INPUT_PULLUP);
  spi.begin(PIN_SCLK, PIN_MISO, PIN_MOSI, -1);
  delay(200);                                   // power-on reset: 2^18 tCLK = 128 ms
  digitalWrite(PIN_RESET, LOW); delayMicroseconds(10); digitalWrite(PIN_RESET, HIGH);
  delayMicroseconds(20);                        // 18 tCLK
  op(0, SDATAC);
  writeReg(0, CONFIG1, 0xE4);                   // master: CLK_EN so the slave gets a clock
  delay(2);
  op(1, RESET);                                 // the slave now has a clock: reset it properly
  delayMicroseconds(20);
  op(1, SDATAC);
  for (int c = 0; c < NCHIP; c++) writeReg(c, CONFIG3, 0xC0);  // internal reference on
  delay(150);                                   // reference settling
}

bool configure(int fs, int gain, Mode mode, bool leadoff) {
  int dr = drCode(fs), g = gainCode(gain);
  if (dr < 0 || g < 0) return false;
  for (int c = 0; c < NCHIP; c++) {
    bool master = c == 0;
    writeReg(c, CONFIG1, 0x80 | 0x40 | (master ? 0x20 : 0) | dr);
    writeReg(c, CONFIG2, mode == TEST ? 0x10 : 0x00);         // internal test: 1 mV, fCLK/2^21
    // Refbuf on, RLDREF internal; only the master drives the right-leg (RLD) electrode.
    writeReg(c, CONFIG3, master ? 0xCC : 0xC8);
    writeReg(c, LOFF, 0x00);                                  // DC lead-off, 6 nA, 95% threshold
    for (int ch = 0; ch < 8; ch++) writeReg(c, CH1SET + ch, (g << 4) | mode);
    uint8_t rld = (master && mode == NORMAL) ? 0xFF : 0x00;
    writeReg(c, RLD_SENSP, rld);
    writeReg(c, RLD_SENSN, rld);
    uint8_t lo = (leadoff && mode == NORMAL) ? 0xFF : 0x00;
    writeReg(c, LOFF_SENSP, lo);
    writeReg(c, LOFF_SENSN, lo);
    writeReg(c, LOFF_FLIP, 0x00);
    writeReg(c, GPIO, 0x0F);                                  // GPIO1-4 inputs (tied to DGND on the board)
    writeReg(c, CONFIG4, lo ? 0x02 : 0x00);                   // lead-off comparators
    writeReg(c, WCT1, 0x00);
    writeReg(c, WCT2, 0x00);
  }
  return true;
}

void startStream() {
  for (int c = 0; c < NCHIP; c++) op(c, RDATAC);
  digitalWrite(PIN_START, HIGH);
}

void stopStream() {
  digitalWrite(PIN_START, LOW);
  for (int c = 0; c < NCHIP; c++) op(c, SDATAC);
}

void readFrame(uint8_t* out) {
  spi.beginTransaction(cfg);
  for (int c = 0; c < NCHIP; c++) {
    digitalWrite(cs[c], LOW);
    memset(out, 0, FRAME);
    spi.transferBytes(out, out, FRAME);  // DIN held low while reading
    digitalWrite(cs[c], HIGH);
    out += FRAME;
  }
  spi.endTransaction();
}
}  // namespace ads
