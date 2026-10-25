/*
 * SilentSOS ESP32 firmware — discreet emergency alert button.
 *
 * Implements docs/PROTOCOL.md exactly:
 *   - JSON payload {"ts","lat","lon","battery","type"}, AES-256-GCM with the
 *     device key, fresh 12-byte nonce per message (esp_random()),
 *     device_id as additional authenticated data (AAD)
 *   - envelope {"device_id","nonce","ciphertext","tag"} (base64 fields)
 *     POSTed to {SERVER_URL}/api/alert
 *
 * Button (GPIO 4, INPUT_PULLUP, active LOW, 50 ms debounce via interrupt):
 *   3 presses within 2 s -> type "alert"     (30 s cooldown between alerts)
 *   3 s hold              -> type "safe"
 * While an alert is active, type "update" is sent every 15 s.
 * Vibration motor (GPIO 5): 1 short pulse = accepted (HTTP 200),
 * 3 short pulses = failed after retries (exponential backoff, max 3 tries).
 *
 * Secrets live in config.h (git-ignored); see config.example.h.
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include "mbedtls/gcm.h"
#include "mbedtls/base64.h"
#include "esp_system.h"   // esp_random()

#include "config.h"

#if USE_GPS
#include <TinyGPSPlus.h>
#endif

// ---------------- pins ----------------
#define BUTTON_PIN   4
#define VIB_PIN      5
#define GPS_RX_PIN   16   // ESP32 RX2 <- NEO-6M TX
#define GPS_TX_PIN   17   // ESP32 TX2 -> NEO-6M RX

// ---------------- protocol constants (match docs/PROTOCOL.md) ----------------
#define NONCE_LEN          12
#define TAG_LEN            16
#define KEY_LEN            32
#define DEBOUNCE_MS        50
#define PRESS_WINDOW_MS    2000
#define PRESSES_FOR_ALERT  3
#define HOLD_MS            3000
#define COOLDOWN_S         30
#define UPDATE_INTERVAL_MS 15000   // 4/min: stays under the 5/min server
                                  // rate limit (see README)
#define MAX_TRIES          3

// ---------------- state ----------------
static uint8_t deviceKey[KEY_LEN];
static bool dryRun = false;

static bool alertActive = false;
static unsigned long lastAlertMs = 0;     // millis() of last sent alert
static unsigned long lastUpdateMs = 0;

// button state machine
static volatile unsigned long isrLastMs = 0;
static volatile unsigned long isrPressMs = 0;
static volatile bool pressEvent = false;
static bool pressInProgress = false;
static bool holdFired = false;
static unsigned long pressDownMs = 0;
static unsigned long pressTimes[PRESSES_FOR_ALERT] = {0, 0, 0};

#if USE_GPS
static TinyGPSPlus gps;
static HardwareSerial gpsSerial(2);
#endif

// ---------------- helpers ----------------

void vibrate(int pulses) {
  for (int i = 0; i < pulses; i++) {
    digitalWrite(VIB_PIN, HIGH);
    delay(200);
    digitalWrite(VIB_PIN, LOW);
    if (i + 1 < pulses) delay(150);
  }
}

void IRAM_ATTR onButtonFall() {
  unsigned long now = millis();
  if (now - isrLastMs > DEBOUNCE_MS) {   // 50 ms debounce
    isrLastMs = now;
    isrPressMs = now;
    pressEvent = true;
  }
}

void getPosition(float *lat, float *lon) {
#if USE_GPS
  if (gps.location.isValid() && gps.location.age() < 5000) {
    *lat = gps.location.lat();
    *lon = gps.location.lng();
    return;
  }
  // fall through to fixed coordinates until the GPS has a fix
#endif
  *lat = FIXED_LAT;
  *lon = FIXED_LON;
}

// base64-encode; returns false if the output buffer is too small
bool b64enc(const uint8_t *in, size_t inLen, char *out, size_t outSize) {
  size_t olen = 0;
  if (mbedtls_base64_encode((unsigned char *)out, outSize, &olen,
                             in, inLen) != 0) {
    return false;
  }
  out[olen] = '\0';
  return true;
}

int httpPost(const char *path, const char *body) {
  char url[220];
  snprintf(url, sizeof(url), "%s%s", SERVER_URL, path);
  HTTPClient http;
  int code;
  if (strncmp(SERVER_URL, "https://", 8) == 0) {
    WiFiClientSecure cli;
    cli.setInsecure();  // demo: no CA validation (see README)
    http.begin(cli, url);
    http.addHeader("Content-Type", "application/json");
    code = http.POST((uint8_t *)body, strlen(body));
  } else {
    WiFiClient cli;
    http.begin(cli, url);
    http.addHeader("Content-Type", "application/json");
    code = http.POST((uint8_t *)body, strlen(body));
  }
  http.end();
  return code;
}

// Build the plaintext JSON, encrypt with AES-256-GCM (fresh nonce per call),
// and POST the envelope. Retries with exponential backoff (max 3 tries).
// Returns true on HTTP 200.
bool sendMessage(const char *type) {
  float lat, lon;
  getPosition(&lat, &lon);

  for (int attempt = 1; attempt <= MAX_TRIES; attempt++) {
    time_t now = time(nullptr);
    char plaintext[160];
    snprintf(plaintext, sizeof(plaintext),
             "{\"ts\":%ld,\"lat\":%.4f,\"lon\":%.4f,"
             "\"battery\":%d,\"type\":\"%s\"}",
             (long)now, lat, lon, BATTERY_PCT, type);

    uint8_t nonce[NONCE_LEN];
    for (int i = 0; i < NONCE_LEN; i += 4) {
      uint32_t r = esp_random();
      memcpy(nonce + i, &r, 4);
    }

    uint8_t ct[160];
    uint8_t tag[TAG_LEN];
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES,
                                deviceKey, KEY_LEN * 8);
    size_t ptLen = strlen(plaintext);
    if (rc == 0) {
      rc = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, ptLen,
                                     nonce, NONCE_LEN,
                                     (const unsigned char *)DEVICE_ID,
                                     strlen(DEVICE_ID),
                                     (const unsigned char *)plaintext, ct,
                                     TAG_LEN, tag);
    }
    mbedtls_gcm_free(&gcm);
    if (rc != 0) {
      Serial.printf("GCM encrypt failed: %d\n", rc);
      return false;
    }

    char b64nonce[20], b64tag[28], b64ct[224];
    if (!b64enc(nonce, NONCE_LEN, b64nonce, sizeof(b64nonce)) ||
        !b64enc(tag, TAG_LEN, b64tag, sizeof(b64tag)) ||
        !b64enc(ct, ptLen, b64ct, sizeof(b64ct))) {
      Serial.println("base64 encode failed");
      return false;
    }

    char envelope[512];
    snprintf(envelope, sizeof(envelope),
             "{\"device_id\":\"%s\",\"nonce\":\"%s\","
             "\"ciphertext\":\"%s\",\"tag\":\"%s\"}",
             DEVICE_ID, b64nonce, b64ct, b64tag);

    if (dryRun) {
      Serial.println("[dry-run] would POST:");
      Serial.println(envelope);
      return true;
    }

    int code = httpPost("/api/alert", envelope);
    Serial.printf("POST /api/alert type=%s -> HTTP %d (try %d/%d)\n",
                  type, code, attempt, MAX_TRIES);
    if (code == 200) return true;
    if (attempt < MAX_TRIES) delay(attempt * 1000);  // 1s, 2s backoff
  }
  return false;
}

void onTriplePress() {
  if (millis() - lastAlertMs < (unsigned long)COOLDOWN_S * 1000) {
    Serial.println("cooldown: alert suppressed (< 30 s since last)");
    return;
  }
  Serial.println("triple press -> sending alert");
  if (sendMessage("alert")) {
    Serial.println("vibration: 1 short pulse");
    vibrate(1);
    alertActive = true;
    lastAlertMs = millis();
    lastUpdateMs = millis();
  } else {
    Serial.println("vibration: 3 short pulses");
    vibrate(3);
  }
}

void onHold() {
  Serial.println("3 s hold -> sending safe");
  if (sendMessage("safe")) {
    Serial.println("vibration: 1 short pulse");
    vibrate(1);
    alertActive = false;
  } else {
    Serial.println("vibration: 3 short pulses");
    vibrate(3);
  }
}

void registerPress() {
  pressTimes[0] = pressTimes[1];
  pressTimes[1] = pressTimes[2];
  pressTimes[2] = millis();
  Serial.println("press registered");
  if (pressTimes[0] != 0 &&
      pressTimes[2] - pressTimes[0] <= PRESS_WINDOW_MS) {
    pressTimes[0] = pressTimes[1] = pressTimes[2] = 0;
    onTriplePress();
  }
}

// ---------------- setup / loop ----------------

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\nSilentSOS firmware boot");

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(VIB_PIN, OUTPUT);
  digitalWrite(VIB_PIN, LOW);
  attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), onButtonFall, FALLING);

#if USE_GPS
  gpsSerial.begin(9600, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  Serial.println("GPS on UART2 (9600 baud)");
#endif

  // decode the device key
  size_t olen = 0;
  int rc = mbedtls_base64_decode(deviceKey, sizeof(deviceKey), &olen,
                                 (const unsigned char *)DEVICE_KEY_B64,
                                 strlen(DEVICE_KEY_B64));
  if (rc != 0 || olen != KEY_LEN) {
    Serial.println("FATAL: DEVICE_KEY_B64 is not 32 bytes base64");
    while (true) { delay(1000); }
  }

  dryRun = strncmp(SERVER_URL, "https://REPLACE", 15) == 0;
  if (dryRun) {
    Serial.println("DRY-RUN mode: packets are built+encrypted and printed, "
                   "not POSTed");
  }

  // Wi-Fi (empty password = open network, e.g. Wokwi-GUEST)
  Serial.printf("WiFi: connecting to %s\n", WIFI_SSID);
  if (strlen(WIFI_PASSWORD) == 0) {
    WiFi.begin(WIFI_SSID);
  } else {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 30000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi failed; rebooting in 10 s");
    delay(10000);
    ESP.restart();
  }
  Serial.print("WiFi connected, IP: ");
  Serial.println(WiFi.localIP());

  // NTP: the ESP32 has no clock after power-up; sync so ts is valid
  Serial.printf("NTP sync via %s ...\n", NTP_SERVER);
  configTime(GMT_OFFSET_SEC, 0, NTP_SERVER);
  t0 = millis();
  while (time(nullptr) < 1000000000L && millis() - t0 < 15000) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (time(nullptr) < 1000000000L) {
    Serial.println("WARNING: NTP sync failed; timestamps may be rejected");
  } else {
    Serial.print("clock synced: ");
    Serial.println((long)time(nullptr));
  }

  Serial.println("ready: 3x press = alert, 3 s hold = safe");
}

void loop() {
#if USE_GPS
  while (gpsSerial.available()) gps.encode(gpsSerial.read());
#endif

  // --- button state machine ---
  if (pressEvent) {
    pressEvent = false;
    pressDownMs = isrPressMs;   // ISR timestamp, not loop time
    pressInProgress = true;
    holdFired = false;
  }
  if (pressInProgress) {
    if (digitalRead(BUTTON_PIN) == HIGH) {
      pressInProgress = false;          // released
      if (!holdFired) registerPress();  // short press
      holdFired = false;
    } else if (!holdFired && millis() - pressDownMs >= HOLD_MS) {
      holdFired = true;
      pressInProgress = false;  // ignore until release
      onHold();
    }
  }

  // --- periodic updates while an alert is active ---
  if (alertActive && millis() - lastUpdateMs >= UPDATE_INTERVAL_MS) {
    lastUpdateMs = millis();
    Serial.println("sending periodic update");
    if (sendMessage("update")) {
      vibrate(1);
    } else {
      vibrate(3);
    }
  }

  delay(10);
}
