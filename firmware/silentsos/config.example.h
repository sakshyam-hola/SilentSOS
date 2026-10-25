// SilentSOS ESP32 firmware — configuration TEMPLATE.
// Copy to config.h and fill in your values. config.h is git-ignored;
// only this example file is committed.
#pragma once

// --- Wi-Fi ---
// For the Wokwi simulator use SSID "Wokwi-GUEST" with an empty password
// (that is Wokwi's built-in open network).
#define WIFI_SSID       "YourWiFiSSID"
#define WIFI_PASSWORD   "YourWiFiPassword"

// --- Backend ---
// No trailing slash. http:// for local dev, https:// for a public tunnel.
// If it still starts with "https://REPLACE", the firmware runs in DRY-RUN
// mode: it builds + encrypts each packet and prints it instead of POSTing.
#define SERVER_URL      "https://REPLACE-WITH-YOUR-TUNNEL-URL"

// --- Device identity (must match a row in the server registry) ---
#define DEVICE_ID       "dev-001"
// Base64 of the 32-byte AES key (from `python backend/registry.py --seed`).
#define DEVICE_KEY_B64  "paste-base64-key-here"

// --- Position ---
// 0 = send the fixed demo coordinates below.
// 1 = read a NEO-6M GPS on UART2 (RX=GPIO16 <- GPS TX, TX=GPIO17 -> GPS RX)
//     using the TinyGPS++ library.
#define USE_GPS         0
#define FIXED_LAT       27.7172
#define FIXED_LON       85.3240

// --- Misc ---
#define BATTERY_PCT     87          // fixed demo value; wire a divider to an
                                    // ADC pin and replace getBattery() for real use
#define NTP_SERVER      "pool.ntp.org"
#define GMT_OFFSET_SEC  20700       // Kathmandu: UTC+5:45
