# HALO → Arcade: serwer FastAPI z gestami EEG — projekt

## Po co

Grać w gry z Arcade (Tetris, Pong, Runner) gestami rozpoznanymi z EEG opaski HALO. Aplikacja mobilna
(kontrakt `Downloads/WEBSOCKET.md`, v1) wysyła surowe próbki przez WebSocket. Serwer przepuszcza je przez
wytrenowany model `tools/models/gestures.joblib` i każdy rozpoznany gest zamienia na przycisk Arcade
według ustawień. Ustawienia (co robi który gest) zmienia się na stronie serwowanej przez ten sam serwer.

## Cele, nie-cele, anty-cele

- Cel: telefon (EEG albo ręczny pad) → serwer → Arcade, bez ręcznej konfiguracji Arcade (zwykłe `npm run dev`).
- Cel: strona ustawień: przypisanie gest → przycisk osobno dla menu, Tetrisa, Ponga i Runnera, próg pewności
  gestu, podgląd na żywo (gracze, gesty, połączenie z Arcade), przycisk „testuj gest” bez opaski.
- Cel: pełna obsługa kontraktu WEBSOCKET.md (walidacja, rezerwacja gracza, ACK, błędy, tryb manual).
- Nie-cel: douczanie modelu, zmiany w aplikacji macOS, zmiany w kodzie Arcade, logowanie użytkowników.
- Anty-cel: zaległe gesty wykonywane z opóźnieniem (lepiej zgubić gest niż wykonać go sekundę później);
  nadpisanie modelu `gestures.joblib` albo zakłócenie działającej aplikacji BrainGestures.

## Ograniczenia (sprawdzone)

- Dane telefonu = dane treningowe: 250 Hz, O1/O2/Fp2/Fp1 w µV, akcelerometr m/s², żyroskop °/s.
  `gestures.recognizer.GestureRecognizer(channels, fs)` przyjmuje kawałki (kanały × próbki) o dowolnej długości;
  kontakt elektrod czyta z wierszy `contact_<kanał>` (1 = kontakt).
- Model: RandomForest 500 drzew, klasy rest/blink/look_left/look_right/frown/jaw/head_*; jedno okno co 0,1 s,
  ok. 11 ms → ok. 11% rdzenia na gracza. Inferencja musi iść poza pętlą asyncio (wątek).
- Skuteczność u nowej osoby: głowa ~98%, czoło 88%, szczęka 78%, spojrzenia 61–68%, mrugnięcie 50%.
- Arcade: serwer sterowania `ws://localhost:8787` przyjmuje pady (JSON `{"player":1,"button":"left","id":..}`,
  bez `state` = tap 120 ms, `ms` 30–2000), deduplikuje po (player, id) i przesyła padom stan gry
  (`{"type":"state","game":"tetris"|"pong"|"runner"|null,"screen":"hub"|"setup"|"game",...}`).
- Python 3.13; pickle modelu wymaga tych samych wersji co `tools/.venv` (numpy 2.5.4, scipy 1.18.1,
  scikit-learn 1.9.1, joblib 1.6.0).

## Podejścia (rozważone)

1. **Serwer łączy się z Arcade jako pad (wybrane).** Klient WebSocket do `ws://localhost:8787`, ponawianie
   połączenia. Arcade nie wymaga zmiennych środowiskowych; serwer dostaje przy okazji bieżącą grę, więc
   mapowanie może zależeć od gry.
2. Arcade łączy się do serwera (`ARCADE_UPSTREAM=ws://…`). Działa, ale wymaga restartu Arcade ze zmienną
   i nie daje informacji, która gra jest włączona.
3. Serwer wysyła HTTP `/api/input`. Prostsze, ale osobne połączenie na każde zdarzenie i też brak stanu gry.

Ekran ustawień: strona serwowana przez FastAPI (wybór użytkownika), nie ekran w Arcade.

## Projekt

### Układ plików (`backend/`, katalog już istnieje i jest pusty)

```
backend/
  app.py          FastAPI: /ws/controller, /ws/ui, /api/settings, /api/test, strona /
  protocol.py     walidacja wiadomości WEBSOCKET.md v1 (czyste funkcje, bez I/O)
  sessions.py     rezerwacja graczy, sesje EEG/manual, worker rozpoznawania
  arcade.py       klient WebSocket do Arcade (ponawianie, stan gry, wysyłanie przycisków)
  settings.py     domyślne mapowania, zapis/odczyt settings.json, walidacja
  static/index.html   strona ustawień (czysty HTML/JS, bez budowania)
  sim_phone.py    atrapa telefonu: odtwarza sesję z tools/training/sessions/*/eeg.csv albo manual
  tests/          pytest
  requirements.txt, README.md, run.sh
```

Kod modelu importowany z `tools/` (dopisanie ścieżki do `sys.path`), model tylko czytany.
Własne środowisko `backend/.venv` (fastapi, uvicorn[standard], websockets + wersje numpy/scipy/sklearn/joblib
jak w `tools/.venv`), żeby nie ruszać środowiska działającej aplikacji.

### `/ws/controller` (WEBSOCKET.md v1)

- Opcjonalny token: zmienna `HALO_TOKEN`; ustawiona i niezgodna z `Authorization: Bearer` → odrzucenie upgrade (403).
- `hello` w 5 s, wersja 1, UUID, `role:"controller"`, gracz 1/2, `mode` brak/`eeg`/`manual`.
  EEG: `sample_rate_hz` 250, kanały zawierają O1/O2/Fp2/Fp1, `layout:"sample_major"`, `has_accel` i `has_gyro`
  → inaczej `error unsupported_stream`.
- Rezerwacja gracza atomowa (jeden słownik + lock); zajęty → `error player_busy` i zamknięcie.
  Zwolnienie tylko przez sesję-właściciela.
- `ready` raz (w manual z `mode:"manual"`).
- `samples`: walidacja typów/długości/skończoności, `seq` dokładnie +1, zgodność z `hello`; błąd →
  `error invalid_packet` + zamknięcie. Przyjęty pakiet → kolejka analizy sesji → `ack` z tym `seq`
  (każdy pakiet). Nieciągłość `first_sample_index` albo wiersze `is_dummy` → reset rozpoznawania
  (nowy GestureRecognizer z przeniesionym tłem osoby; wiersze dummy wyrzucone). Kontakt pakietu
  rozpisany na wiersze `contact_*` (recognizer sam nie zgłasza gestów bez kontaktu).
- Kolejka analizy ograniczona (~2 s danych); przepełnienie → wyrzucenie najstarszych i reset jak przy luce.
  Gest z danych starszych niż 1 s (wg czasu przyjęcia pakietu) jest pomijany.
- Cisza > 3 s po `ready` w EEG → zamknięcie 1001 (telefon ponowi). Manual: bez limitu ciszy; martwe
  połączenia wykrywa ping uvicorna (co 5 s, limit 10 s).
- `manual`: `seq` +1, `id == "<session_id>:<seq>"`, gracz, przycisk z listy, `action:"press"` → tap do Arcade
  (ten sam przycisk) + `ack`. Zła wiadomość → `error invalid_packet`. `samples` w manual / `manual` w EEG → błąd.
- `stop` → zamknięcie 1000. Nieznany typ, binarna ramka, zły JSON/wersja/sesja → `error` + zamknięcie.
  Maks. rozmiar wiadomości 1 MiB.
- Podgląd do telefonu: `{"type":"input",...,"direction":...}` tylko gdy gest dał left/right/up/down.

### Mapowanie gestów

- Profile: `menu` (ekrany hub/setup), `tetris`, `pong`, `runner`. Profil wybierany z bieżącego stanu Arcade;
  brak stanu → `menu`.
- Każdy wpis: gest → `{button: up|down|left|right|a|b|x|start|select|null, ms: 30–2000}`.
- Próg pewności na gest (wspólny dla gier), domyślnie próg z modelu; wpisywany do `recognizer.thresholds`.
- Domyślnie: menu: głowa → kierunki, szczęka → a, czoło → b; Tetris: głowa lewo/prawo → ruch, góra → obrót,
  dół → down 400 ms, szczęka → a (upuść), czoło → b; Pong: głowa góra/dół → up/down 300 ms; Runner: głowa →
  kierunki (skok/ślizg/pasy), szczęka → a, czoło → b. Mrugnięcie i spojrzenia domyślnie wyłączone.
- Gest gracza N steruje graczem N w Arcade. Id zdarzenia `eeg:<session_id>:<n>` (deduplikacja w Arcade).
- Zapis do `backend/settings.json` (atomowo: plik tymczasowy + rename).

### Strona ustawień (`/`)

- Pasek stanu: połączenie z Arcade + bieżąca gra; adres dla telefonu `ws://<IP>:8000/ws/controller`.
- Karta gracza 1 i 2: tryb, urządzenie, bateria, kontakt elektrod, pakiety/ACK, rozgrzewka, słupki
  prawdopodobieństw, ostatnie gesty → jaki przycisk poszedł.
- Tabela: wiersz = gest (nazwa PL + skuteczność u nowej osoby), kolumny = profile (lista przycisków + ms),
  suwak progu, przycisk „test” (wysyła zmapowany przycisk dla gracza 1/2 bez opaski). Zapis od razu po zmianie.
- Odświeżanie przez `/ws/ui` (stan co ~0,2 s).

### Testy

- pytest + TestClient: hello/ready (EEG i manual), zły hello, zajęty gracz, zwolnienie tylko przez właściciela,
  walidacja samples, ack, manual → Arcade, mapowanie per gra, zapis ustawień.
- `sim_phone.py`: odtwarza nagranie sesji głowy w czasie rzeczywistym przez `/ws/controller`; test końcowy
  z atrapą Arcade (serwer WS) sprawdza, że dochodzą przyciski, oraz ręcznie z działającym Arcade.

## Decyzje budującego (do sprawdzenia)

- Serwer słucha na `0.0.0.0:8000` (zmienna `PORT`), żeby telefon w tej samej sieci się połączył.
- Adres Arcade domyślnie `ws://localhost:8787`, zmienialny na stronie (zapisywany w ustawieniach).
- Arcade niedostępny → gest widać na stronie z dopiskiem „Arcade offline”, nic nie jest kolejkowane na później.
- Gesty obu graczy są niezależne (osobny rozpoznawacz i tło osoby na sesję); progi pewności wspólne.

## Zostawione budującemu

Kody zamknięcia poza opisanymi, wygląd strony (czytelny, ciemny, w duchu Arcade), szczegóły logów.
