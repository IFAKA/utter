// Utter firmware: 2x ADS1298 (16 ch) -> UDP packets per docs/PROTOCOL.md.
// Safety: acquisition is refused/stopped while USB VBUS is present (battery-only recording).
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
#include "ads1298.h"
#include "pins.h"

constexpr uint16_t DATA_PORT = 47700, CTRL_PORT = 47701, MAGIC = 0x4253;
constexpr int NFRAMES = 20, HDR = 24, IMU_BYTES = 12;
constexpr int PKT_MAX = HDR + NFRAMES * ads::NCH * 3 + IMU_BYTES;
constexpr int POOL = 8;
enum Flags : uint8_t { FL_IMU = 1, FL_TEST = 2, FL_SHORTED = 4, FL_VBUS = 8 };

struct Pkt { uint8_t b[PKT_MAX]; int len; };
static Pkt pool[POOL];
static QueueHandle_t ready, freeq;    // packet indices
static TaskHandle_t sampler;
static WiFiUDP ctrl, data;
static Preferences prefs;
static IPAddress dest;
static uint16_t destPort = DATA_PORT;
static volatile bool streaming = false;
static int cfgFs = 2000, cfgGain = 12;
static ads::Mode cfgMode = ads::NORMAL;
static uint8_t chipIds[2];
static uint8_t imuAddr = 0;
static uint32_t lostLocal = 0;

static bool vbus() { return digitalRead(PIN_VBUS) == HIGH; }
static constexpr float VBAT_MIN = 3.55f;
static float vbat() { return analogReadMilliVolts(PIN_VBAT) * 2 / 1000.0f; }

static void IRAM_ATTR onDrdy() {
  BaseType_t hp = pdFALSE;
  vTaskNotifyGiveFromISR(sampler, &hp);
  if (hp) portYIELD_FROM_ISR();
}

// ---- IMU (optional LSM6DS3-family module on the I2C connector) ----
static void imuBegin() {
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  for (uint8_t a : {0x6A, 0x6B}) {
    Wire.beginTransmission(a); Wire.write(0x0F);
    if (Wire.endTransmission(false) != 0 || Wire.requestFrom(a, (uint8_t)1) != 1) continue;
    uint8_t who = Wire.read();
    if (who == 0x69 || who == 0x6A || who == 0x6C) { imuAddr = a; break; }
  }
  if (!imuAddr) return;
  auto wr = [](uint8_t r, uint8_t v) { Wire.beginTransmission(imuAddr); Wire.write(r); Wire.write(v); Wire.endTransmission(); };
  wr(0x10, 0x40);  // CTRL1_XL: 104 Hz, +-2 g
  wr(0x11, 0x40);  // CTRL2_G: 104 Hz, 250 dps
  wr(0x12, 0x44);  // CTRL3_C: BDU, auto-increment
}

static bool imuRead(int16_t* v) {  // ax ay az gx gy gz
  if (!imuAddr) return false;
  Wire.beginTransmission(imuAddr); Wire.write(0x22);  // OUTX_L_G: gyro xyz, then accel xyz
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(imuAddr, (uint8_t)12) != 12) return false;
  int16_t r[6];
  for (int i = 0; i < 6; i++) { uint8_t lo = Wire.read(), hi = Wire.read(); r[i] = (int16_t)(lo | hi << 8); }
  for (int i = 0; i < 3; i++) { v[i] = r[i + 3]; v[i + 3] = r[i]; }
  return true;
}

// ---- acquisition ----
static void samplerTask(void*) {
  uint8_t frame[ads::NCHIP * ads::FRAME];
  int cur = -1, n = 0;
  uint32_t seq = 0, sample = 0, loffP = 0, loffN = 0;
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    if (!streaming) { cur = -1; n = 0; seq = 0; sample = 0; continue; }
    ads::readFrame(frame);
    if (cur < 0) {
      int idx;
      if (xQueueReceive(freeq, &idx, 0) != pdTRUE) { lostLocal++; sample++; continue; }  // net stalled
      cur = idx; n = 0;
    }
    uint8_t* p = pool[cur].b + HDR + n * ads::NCH * 3;
    for (int c = 0; c < ads::NCHIP; c++) {
      const uint8_t* f = frame + c * ads::FRAME;
      uint32_t st = (uint32_t)f[0] << 16 | f[1] << 8 | f[2];  // 1100 | LOFF_STATP | LOFF_STATN | GPIO
      loffP = (loffP & ~(0xFFu << (8 * c))) | ((st >> 12) & 0xFF) << (8 * c);
      loffN = (loffN & ~(0xFFu << (8 * c))) | ((st >> 4) & 0xFF) << (8 * c);
      memcpy(p + c * 24, f + 3, 24);
    }
    if (++n < NFRAMES) continue;
    uint8_t* h = pool[cur].b;
    uint8_t flags = (cfgMode == ads::TEST ? FL_TEST : 0) | (cfgMode == ads::SHORTED ? FL_SHORTED : 0);
    uint32_t first = sample;
    sample += NFRAMES;
    uint16_t fs = cfgFs;
    memcpy(h + 0, &MAGIC, 2); h[2] = 1; h[3] = ads::NCH;
    memcpy(h + 4, &seq, 4); memcpy(h + 8, &first, 4); memcpy(h + 12, &fs, 2);
    h[14] = NFRAMES; h[15] = flags;
    memcpy(h + 16, &loffP, 4); memcpy(h + 20, &loffN, 4);
    pool[cur].len = HDR + NFRAMES * ads::NCH * 3;
    seq++;
    xQueueSend(ready, &cur, 0);
    cur = -1;
  }
}

static void startAcq() {  // chips already configured
  int idx;
  while (xQueueReceive(ready, &idx, 0) == pdTRUE) xQueueSend(freeq, &idx, 0);
  streaming = true;
  ads::startStream();
  attachInterrupt(PIN_DRDY1, onDrdy, FALLING);
}

static void stopAcq() {
  if (!streaming) return;
  detachInterrupt(PIN_DRDY1);
  streaming = false;
  xTaskNotifyGive(sampler);  // let the sampler drop its partial packet
  delay(2);
  ads::stopStream();
}

// ---- control (UDP and USB serial share one handler) ----
static String handle(const String& line, bool fromSerial, IPAddress from) {
  JsonDocument in, out;
  if (deserializeJson(in, line)) { out["ok"] = false; out["err"] = "bad json"; }
  else {
    String cmd = in["cmd"] | "";
    out["ok"] = true;
    if (cmd == "info") {
      out["fw"] = FW_VERSION;
      JsonArray ids = out["chip_ids"].to<JsonArray>();
      ids.add(chipIds[0]); ids.add(chipIds[1]);
      out["vbat"] = roundf(vbat() * 100) / 100;
      out["vbus"] = vbus();
      out["imu"] = imuAddr != 0;
      out["ip"] = WiFi.localIP().toString();
      out["ssid"] = prefs.getString("ssid", "");
      out["streaming"] = (bool)streaming;
      out["dropped"] = lostLocal;
    } else if (cmd == "subscribe") {
      dest = from; destPort = in["port"] | DATA_PORT;
    } else if (cmd == "start") {
      int fs = in["fs"] | cfgFs, gain = in["gain"] | cfgGain;
      String m = in["mode"] | "normal";
      bool lo = in["leadoff"] | true;
      ads::Mode mode = m == "test" ? ads::TEST : m == "shorted" ? ads::SHORTED : ads::NORMAL;
      if (vbus()) { out["ok"] = false; out["err"] = "vbus"; }
      else if (vbat() < VBAT_MIN) { out["ok"] = false; out["err"] = "low battery"; }
      else {
        stopAcq();
        if (!ads::configure(fs, gain, mode, lo)) { out["ok"] = false; out["err"] = "bad fs/gain"; }
        else {
          if (!dest && !fromSerial) dest = from;
          cfgFs = fs; cfgGain = gain; cfgMode = mode;
          startAcq();
        }
      }
    } else if (cmd == "stop") {
      stopAcq();
    } else if (cmd == "regs") {
      if (streaming) { out["ok"] = false; out["err"] = "streaming"; }
      else for (int c = 0; c < 2; c++) {
        JsonArray r = out["chip" + String(c)].to<JsonArray>();
        for (int i = 0; i < ads::NREGS; i++) r.add(ads::readReg(c, i));
      }
    } else if (cmd == "wifi" && fromSerial) {
      String ssid = in["ssid"] | "", pass = in["pass"] | "";
      WiFi.disconnect();
      WiFi.begin(ssid.c_str(), pass.c_str());
      uint32_t t0 = millis();
      while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(100);
      if (WiFi.status() == WL_CONNECTED) {
        prefs.putString("ssid", ssid); prefs.putString("pass", pass);
        out["ip"] = WiFi.localIP().toString();
      } else { out["ok"] = false; out["err"] = "connect failed"; }
    } else { out["ok"] = false; out["err"] = "unknown cmd " + cmd; }
  }
  String s;
  serializeJson(out, s);
  return s;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_VBUS, INPUT);  // external divider; pulled to GND when no USB
  analogReadResolution(12);
  prefs.begin("utter");
  ready = xQueueCreate(POOL, sizeof(int));
  freeq = xQueueCreate(POOL, sizeof(int));
  for (int i = 0; i < POOL; i++) xQueueSend(freeq, &i, 0);
  xTaskCreatePinnedToCore(samplerTask, "ads", 4096, nullptr, configMAX_PRIORITIES - 1, &sampler, 1);
  ads::begin();
  for (int c = 0; c < 2; c++) chipIds[c] = ads::readReg(c, ads::ID);
  imuBegin();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // latency over power: modem sleep adds 100+ ms jitter
  WiFi.setHostname("utter");
  String ssid = prefs.getString("ssid", "");
  if (ssid.length()) WiFi.begin(ssid.c_str(), prefs.getString("pass", "").c_str());
}

void loop() {
  static bool mdnsUp = false, udpUp = false;
  static String serialLine;
  static uint32_t lastBlink = 0;

  if (streaming && vbus()) stopAcq();  // safety: never record while tethered to a mains device
  static uint32_t lastVbat = 0;  // AP2112 dropout: below ~3.55 V Wi-Fi bursts brown out the ESP32
  if (streaming && millis() - lastVbat > 1000) { lastVbat = millis(); if (vbat() < VBAT_MIN - 0.05f) stopAcq(); }

  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') { if (serialLine.length()) Serial.println(handle(serialLine, true, IPAddress())); serialLine = ""; }
    else if (ch != '\r' && serialLine.length() < 512) serialLine += ch;
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!udpUp) { ctrl.begin(CTRL_PORT); udpUp = true; }
    if (!mdnsUp && MDNS.begin("utter")) { MDNS.addService("utter", "udp", CTRL_PORT); mdnsUp = true; }
    int len = ctrl.parsePacket();
    if (len > 0 && len < 1024) {
      char buf[1024];
      int n = ctrl.read(buf, sizeof(buf) - 1);
      buf[n] = 0;
      String reply = handle(String(buf), false, ctrl.remoteIP());
      ctrl.beginPacket(ctrl.remoteIP(), ctrl.remotePort());
      ctrl.print(reply);
      ctrl.endPacket();
    }
  } else if (udpUp) { ctrl.stop(); udpUp = false; MDNS.end(); mdnsUp = false; }

  int idx;
  while (xQueueReceive(ready, &idx, 0) == pdTRUE) {
    Pkt& p = pool[idx];
    int16_t imu[6];
    if (imuRead(imu)) { memcpy(p.b + p.len, imu, IMU_BYTES); p.len += IMU_BYTES; p.b[15] |= FL_IMU; }
    if (dest && WiFi.status() == WL_CONNECTED) {
      data.beginPacket(dest, destPort);
      data.write(p.b, p.len);
      data.endPacket();
    }
    xQueueSend(freeq, &idx, 0);
  }

  uint32_t now = millis();  // LED: solid = streaming, 1 Hz = Wi-Fi ok, fast = no Wi-Fi
  uint32_t period = streaming ? 0 : WiFi.status() == WL_CONNECTED ? 1000 : 200;
  if (!period) digitalWrite(PIN_LED, HIGH);
  else if (now - lastBlink > period / 2) { lastBlink = now; digitalWrite(PIN_LED, !digitalRead(PIN_LED)); }
  if (!streaming) delay(1);
}
