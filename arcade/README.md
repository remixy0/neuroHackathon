# ARCADE – Tetris, Pong i Runner w jednym programie

Trzy gry w jednym programie, z jednym menu, jednym wyglądem (szara obudowa, czarny ekran, pikselowa czcionka) i **jednym API sterowania**.
Każde urządzenie, które umie wysłać „gracz 1, przycisk w lewo”, steruje każdą z gier: klawiatura, gamepad, telefon, ESP32, Raspberry Pi, skrypt albo backend rozpoznawania gestów.

Gry są po angielsku. Projekt powstał z trzech osobnych klonów (`tetris-react`, `Pong`, `subway`), które zostają nietknięte obok. Runner to dawny HALO RUSH z folderu `subway`.

## Uruchomienie

Wymagany Node.js 20.19 lub nowszy.

```bash
npm install
npm run dev
```

Gra działa pod adresem wypisanym przez Vite (zwykle http://localhost:5173).
Razem z nią startuje serwer sterowania:

- WebSocket i HTTP na porcie **8787**,
- UDP na porcie **8788**.

W konsoli zobaczysz adres pada na telefon, np. `http://192.168.1.20:8787/?player=1`.
Telefon i mikrokontrolery muszą być w tej samej sieci co komputer.
Gdy Windows zapyta o zaporę, zezwól w sieci prywatnej.

Pozostałe polecenia:

- `npm run build` buduje wersję produkcyjną do `dist/`.
- `npm run preview` uruchamia zbudowaną wersję (serwer sterowania też startuje).
- `npm run relay` uruchamia sam serwer sterowania.
- `npm test` uruchamia testy protokołu i logiki Runnera.
- `npm run mock:halo` uruchamia atrapę backendu HALO (patrz niżej).

## Gry

| Gra | Gracze | Opcje w menu |
|---|---|---|
| TETRIS | 1 lub 2 | tryb (MARATHON, SPRINT 40, ULTRA, MOST LINES, SURVIVAL), czas, śmieci, poziom |
| PONG | 1 (przeciw komputerowi) lub 2 | poziom komputera, do ilu punktów |
| RUNNER | 1 lub 2 | czas biegu (60, 90 albo 120 s) |

Runner działa jak Subway Surfers. Tor składa się z rzędów przeszkód, które wymuszają ruch:

- płotki na wszystkich pasach – trzeba skoczyć,
- belki na wszystkich pasach – trzeba się wślizgnąć,
- długie pociągi na dwóch pasach – trzeba zmienić pas i na nim zostać (wjechanie w bok pociągu też boli),
- mieszane rzędy (pociąg, płotek, belka) i zygzaki pociągów, w których wolny pas co chwilę się zmienia.

Z każdą sekundą robi się szybciej i gęściej.

Menu główne → gra → ustawienia → START. W trakcie gry START albo SELECT otwiera pauzę (RESUME, RESTART, MENU).
Po grze pojawia się tabela wyników.

## Wirtualny pad

Każdy gracz ma ten sam wirtualny pad. Gry rozumieją przyciski tak:

| Przycisk | Menu | Tetris | Pong | Runner |
|---|---|---|---|---|
| `up` | w górę | obrót w prawo | paletka w górę | skok |
| `down` | w dół | szybsze opadanie | paletka w dół | ślizg |
| `left` / `right` | zmiana wartości | ruch | – | zmiana pasa |
| `a` | zatwierdź | upuść od razu | – | skok |
| `b` | wstecz | obrót w lewo | – | ślizg |
| `x` | – | hold | – | – |
| `start` | zatwierdź; w ustawieniach gry od razu START | pauza | pauza | pauza |
| `select` | wstecz | pauza | pauza | pauza |
| `pos` (0..1) | – | – | pozycja paletki (potencjometr) | – |

Masz tylko dwa przyciski (góra/dół)? Wciśnięcie obu naraz w menu działa jak „zatwierdź”.
W Pongu przytrzymanie obu przez 1 s włącza pauzę.

W grze dla jednej osoby oba zestawy przycisków sterują tym samym graczem.

### Klawiatura

W menu, w Pongu i w Runnerze:

| | Gracz 1 | Gracz 2 |
|---|---|---|
| up / down / left / right | W / S / A / D | ↑ / ↓ / ← / → |
| a | Spacja, E | Enter, Num 0 |
| b | Q | `/`, prawy Ctrl |
| x | lewy Shift, R | prawy Shift, `.` |
| start | P | – |
| select | Esc, Backspace | – |

W trakcie gry w Tetrisa obowiązuje jego dawny układ klawiszy:

| | Gracz 1 | Gracz 2 | Gra solo (dodatkowo) |
|---|---|---|---|
| ruch | A / D | ← / → | |
| szybsze opadanie | S | ↓ | |
| upuść od razu | Spacja | Enter / Num 0 | |
| obrót w prawo | W | ↑ | X |
| obrót w lewo | Q | `/` / prawy Ctrl | Z |
| hold | E / lewy Shift | prawy Shift / `.` | C |

W grze solo działają oba zestawy. Pauza: P albo Esc.

M wycisza dźwięk, F włącza pełny ekran.

### Gamepad

Działa bez konfiguracji: pierwszy pad to gracz 1, drugi pad to gracz 2.

| Wejście gamepada | Przycisk |
|---|---|
| krzyżak albo lewa gałka | up / down / left / right |
| A | a |
| B | b |
| X, Y albo bumpery | x |
| Start | start |
| Back | select |

## API sterowania

### Format komunikatu

JSON:

```json
{"player": 1, "button": "left", "state": "down"}
{"player": 1, "button": "left", "state": "up"}
{"player": 2, "button": "a"}
{"player": 2, "pos": 0.42}
```

Albo jedna komenda tekstowa w linii (wygodne na mikrokontrolerach):

```
1 left down
P1 LEFT PRESS
P1 LEFT RELEASE
2 a
P2 UP TAP 150
P1 POS 0.42
P2 RAW 512 1023
START
```

Pola:

- `player`: `1` albo `2` (także `"p1"`, `"P2"`). Domyślnie `1`.
- `button`: `up`, `down`, `left`, `right`, `a`, `b`, `x`, `start`, `select`.
- `state`: `down` (wciśnięty), `up` (puszczony) albo pominięty. Pominięty oznacza krótkie naciśnięcie (`tap`, 120 ms, długość można podać w `ms`).
  Akceptowane są też `press`/`release`, `1`/`0`, `on`/`off`.
- `pos`: pozycja analogowa 0..1. Alternatywnie `raw` + `max` (np. ADC 0..1023 albo 0..4095).
- `id`: opcjonalny identyfikator zdarzenia. Ta sama para (player, id) wykona się tylko raz.

Przycisk wysłany jako `down` bez `up` puszcza się sam po 5 s (zabezpieczenie przed zgubionym pakietem).
Trzymając dłużej, ponawiaj `down` co ok. 1 s. Pady z przykładów już to robią.
Gdy pad WebSocket się rozłączy, serwer puszcza wszystkie jego przyciski.

Stare formaty działają dalej:

- Tetris: `{"player":1,"action":"hard"}`, gdzie `soft`, `hard`, `cw`, `ccw` i `hold` to odpowiednio `down`, `a`, `up`, `b` i `x`.
- Pong: `P1 UP PRESS` oraz `/api/button?player=1&button=up&action=press` i `/api/paddle`.
- Runner (dawny HALO RUSH) i backend HALO: `{"type":"input","player":1,"direction":"left","id":7}`.

### Sposoby wysłania

| Sposób | Adres | Uwagi |
|---|---|---|
| WebSocket | `ws://<IP>:8787` | dowolna liczba padów, komunikat = JSON albo tekst |
| HTTP | `GET`/`POST http://<IP>:8787/api/input?player=1&button=left&state=down` | też JSON albo tekst w treści zapytania |
| HTTP (tekst) | `/api/cmd?c=P1 LEFT PRESS` albo `POST /api/cmd` | kilka linii naraz |
| UDP | `<IP>:8788` | jedna lub kilka linii; serwer odpowiada `OK n` albo `ERR` |
| Pad na telefon | `http://<IP>:8787/?player=1` | wygląd klasycznego kontrolera NES: krzyżak, START nad SELECT, X obok A nad B (X to hold w Tetrisie), duże litery na przyciskach, ekran z wynikiem, tryb „Knob” (pokrętło do Ponga); działa pionowo i poziomo |
| Backend jako serwer | `ARCADE_UPSTREAM=ws://host:port` | serwer gry sam łączy się z Twoim serwerem WebSocket |

`GET /api` zwraca opis API i adresy w sieci lokalnej. CORS jest otwarty.

```bash
curl "http://localhost:8787/api/input?player=1&button=left&state=down"
curl "http://localhost:8787/api/input?player=1&button=left&state=up"
curl -X POST -d "P2 A" http://localhost:8787/api/cmd
```

### Informacje zwrotne

- `GET /api/state` zwraca ostatni stan gry. Ten sam stan dostaje co 0,4 s każdy klient WebSocket (np. telefon):

  ```json
  {"type":"state","title":"TETRIS","game":"tetris","screen":"game","state":"playing",
   "players":[{"score":1200,"alive":true,"info":"lines 8  level 1"}],"winner":null}
  ```

- Zdarzenia gry trafiają do klientów WebSocket jako `{"type":"event","event":"..."}`:
  - Pong: `HIT`, `WALL`, `SCORE 3 5`, `WIN 1`,
  - Tetris: `P1 LINES 4`, `P2 OUT`,
  - Runner: `P1 HIT 2`, `P1 OUT`, `WIN 2`.

### Backend HALO (gesty)

Oryginalny HALO RUSH (folder `subway`) łączył się jako klient z backendem rozpoznawania gestów pod `ws://localhost:8765`.
Teraz robi to serwer gry. Wystarczy uruchomić go ze zmienną środowiskową:

```bat
:: Windows cmd
set ARCADE_UPSTREAM=ws://localhost:8765 && npm run dev
```

```powershell
# PowerShell
$env:ARCADE_UPSTREAM="ws://localhost:8765"; npm run dev
```

Backend wysyła dalej `{"type":"input","player":1,"direction":"left","id":"..."}`, a komendy działają we wszystkich trzech grach.
Do testów bez opaski służy `npm run mock:halo` (w nim wpisujesz `1 left`, `2 up`…).

### Inne parametry

- Port zmienisz zmiennymi `ARCADE_PORT` i `ARCADE_UDP` (`ARCADE_UDP=0` wyłącza UDP).
- `ARCADE_VERBOSE=1` wypisuje każde wciśnięcie – przydatne przy sprawdzaniu okablowania.
- Adres serwera w grze: `?ws=192.168.1.20:8787`, a `?ws=off` wyłącza pady sieciowe.

## Przykłady

Pliki `examples/` są przeniesione z Ponga i dostosowane do wspólnego API:

- `test_api.py` – test HTTP i UDP (tylko biblioteka standardowa Pythona),
- `esp32_wifi/` – pad na ESP32 przez Wi-Fi (UDP albo HTTP), 8 przycisków i opcjonalny potencjometr,
- `raspberry_pi_gpio.py` – przyciski na GPIO Raspberry Pi,
- `halo_mock.js` – atrapa backendu HALO.

## Struktura

```
src/input/protocol.js   protokół (wspólny dla przeglądarki i serwera)
src/input/hub.js        klawiatura, gamepad, WebSocket → wirtualny pad
src/games/tetris/       Tetris
src/games/pong/         Pong
src/games/runner/       Runner (Three.js)
src/ui/                 ekrany, menu, pikselowa czcionka
src/App.jsx             menu główne, pauza, wyniki, rozsyłanie wejścia do gier
server/relay.js         serwer sterowania (WebSocket, HTTP, UDP, upstream)
server/pad.html         pad na telefon
```

Nowa gra to katalog w `src/games/` z obiektem: `rows`/`change` (opcje w menu), `create` (mecz z metodami `update`, `press`, `release`, `togglePause`, `snapshot`) i `View` (komponent React).
Dopisujesz ją do listy `GAMES` w `App.jsx` i od razu działa ze wszystkimi sposobami sterowania.
