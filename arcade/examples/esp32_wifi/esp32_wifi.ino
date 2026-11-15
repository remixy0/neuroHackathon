/*
  ARCADE – bezprzewodowy pad na ESP32 (Wi-Fi)
  --------------------------------------------
  Wysyła przyciski do serwera gry przez UDP (domyślnie, najmniejsze opóźnienie)
  albo HTTP (ustaw USE_UDP na 0). Jedno ESP32 = jeden gracz (zmień PLAYER).
  Działa we wszystkich grach: Tetris, Pong, Runner.

  Podłączenie: przyciski między pinem a GND (INPUT_PULLUP):
      GPIO 18 UP   GPIO 19 DOWN   GPIO 21 LEFT   GPIO 22 RIGHT
      GPIO 23 A    GPIO 25 B      GPIO 26 X      GPIO 27 START
  Opcjonalnie potencjometr na GPIO 34 (ADC 0..4095) -> USE_POT 1 (paletka w Pongu)

  SERVER_IP: adres komputera z grą – wypisuje go `npm run dev` ("[arcade] phone pad http://...").
  Dla ESP8266 zamień nagłówki na <ESP8266WiFi.h> i <ESP8266HTTPClient.h>.
*/

#include <WiFi.h>
#include <WiFiUdp.h>
#include <HTTPClient.h>

const char* WIFI_SSID = "NazwaSieci";
const char* WIFI_PASS = "HasloSieci";
const char* SERVER_IP = "192.168.1.100";
const uint16_t HTTP_PORT = 8787;
const uint16_t UDP_PORT  = 8788;
const int PLAYER = 1;                 // 1 albo 2

#define USE_UDP 1
#define USE_POT 0
const int POT_PIN = 34;

struct Btn {
  uint8_t pin;
  const char* name;      // up / down / left / right / a / b / x / start
  bool state;
  bool raw;
  unsigned long changedAt;
  unsigned long sentAt;
};
Btn buttons[] = {
  {18, "UP"}, {19, "DOWN"}, {21, "LEFT"}, {22, "RIGHT"},
  {23, "A"}, {25, "B"}, {26, "X"}, {27, "START"},
};
const uint8_t N = sizeof(buttons) / sizeof(buttons[0]);
const unsigned long DEBOUNCE_MS = 8;
const unsigned long KEEPALIVE_MS = 1000;   // gra puszcza przycisk po 5 s bez sygnału

WiFiUDP udp;

void sendLine(const char* line) {
#if USE_UDP
  udp.beginPacket(SERVER_IP, UDP_PORT);
  udp.print(line);
  udp.endPacket();
#else
  // HTTP: /api/cmd przyjmuje ten sam protokół tekstowy
  HTTPClient http;
  String url = String("http://") + SERVER_IP + ":" + HTTP_PORT + "/api/cmd";
  http.begin(url);
  http.addHeader("Content-Type", "text/plain");
  http.setTimeout(300);
  http.POST(line);
  http.end();
#endif
}

void sendBtn(Btn& b) {
  char line[40];
  snprintf(line, sizeof(line), "P%d %s %s\n", PLAYER, b.name, b.state ? "PRESS" : "RELEASE");
  sendLine(line);
#if USE_UDP
  if (!b.state) sendLine(line);   // UDP może zgubić pakiet – puszczenie wysyłamy 2x
#endif
  b.sentAt = millis();
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < N; i++) {
    pinMode(buttons[i].pin, INPUT_PULLUP);
    buttons[i].state = buttons[i].raw = false;
    buttons[i].changedAt = buttons[i].sentAt = 0;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);               // mniejsze opóźnienia
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.print("\nConnected, IP: ");
  Serial.println(WiFi.localIP());
  udp.begin(UDP_PORT + 10);
}

void loop() {
  unsigned long now = millis();

  for (uint8_t i = 0; i < N; i++) {
    Btn& b = buttons[i];
    bool pressed = digitalRead(b.pin) == LOW;
    if (pressed != b.raw) { b.raw = pressed; b.changedAt = now; }
    if (b.raw != b.state && now - b.changedAt >= DEBOUNCE_MS) {
      b.state = b.raw;
      sendBtn(b);
    } else if (b.state && now - b.sentAt >= KEEPALIVE_MS) {
      sendBtn(b);
    }
  }

#if USE_POT
  static unsigned long potAt = 0;
  static int last = -100;
  if (now - potAt >= 15) {
    potAt = now;
    int v = analogRead(POT_PIN);
    if (abs(v - last) > 12) {
      last = v;
      char line[32];
      snprintf(line, sizeof(line), "P%d RAW %d 4095\n", PLAYER, v);
      sendLine(line);
    }
  }
#endif

  // odpowiedzi serwera (OK/ERR) – czytamy, żeby nie zapchać bufora
  while (udp.parsePacket()) { while (udp.available()) udp.read(); }

  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); delay(200); }
}
