# Kalibracja na starcie sesji i głowa tylko z żyroskopu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serwer HALO → Arcade zgłasza ruchy głowy wyłącznie z żyroskopu, wycisza gesty twarzy przy ruchu głowy, na starcie każdej sesji EEG prowadzi ok. 45 s kalibracji (głos z Maca + strona) i zapisuje sesję na dysk.

**Architecture:** Czysta logika kalibracji w nowym `backend/calibration.py` (kroki liczone w próbkach, bez zegara i bez I/O), głos w `backend/voice.py`, zapis w `backend/recording.py`. `sessions.py` spina je z `EegPipeline`/`EegSession`/`Hub`; `app.py` dostaje jedno nowe API, `static/index.html` pokazuje krok i wynik.

**Tech Stack:** Python 3.13, FastAPI, numpy, pytest (istniejące `backend/.venv`); `say` z macOS.

**Spec:** `docs/superpowers/specs/2026-11-15-kalibracja-i-glowa-z-zyroskopu-design.md`

## Global Constraints

- Serwer na porcie 8000 gra na żywo z telefonem: nie restartować go i nie nadpisywać `backend/settings.json` bez zgody użytkownika. Testy i próby tylko na innych portach i z ustawieniami w katalogu tymczasowym.
- Wspólne stałe w `tools/gestures/recognizer.py` zostają bez zmian (używa ich aplikacja macOS); zachowanie serwera zmieniamy tylko w `backend/`.
- Wartości ze specu: `motion_mute_s` 1,5 s, `motion_mute_dps` 30°/s; spokój 8 s; głowa lewo, prawo, góra, dół po 3 s; twarz: mrugnięcie, szczęka, czoło po 3 razy na przemian po 2,5 s; próg żyroskopu = 0,4 × mediana szczytów w granicach 25–120°/s; próg gestu twarzy = tło + 0,4 × (szczyt − tło) w granicach 0,15–0,95; gest działa, gdy szczyt > tło + 0,08 i co najmniej 2 z 3 prób przekraczają próg.
- `head_gyro` znika z ustawień; stary `settings.json` z tym polem ma się wczytać (nieznane pola są pomijane).
- `backend/recordings/` poza gitem.
- Bez commitów (commit tylko na prośbę użytkownika).
- Testy: `backend/.venv/bin/python -m pytest backend/tests -q` z katalogu repo.

## Review Focus

- Telefon rozłącza się w połowie kalibracji → kolejka kalibracji zwolniona, drugi gracz zaczyna swoją, plik nagrania zamknięty. (Task 4: `test_disconnect_during_calibration_releases_turn`)
- Brak kontaktu elektrod albo luka w danych w kroku gestu twarzy → okna bez kontaktu nie wchodzą do progu; przy mniej niż 2 ważnych próbach gest zostaje na progu globalnym, nie jest wyłączany. (Task 2: `test_face_without_contact_keeps_global`)
- Osoba nie rusza głową w kalibracji (albo rusza w złą stronę) → próg żyroskopu globalny, a nie 25°/s. (Task 2: `test_gyro_too_few_moves_keeps_global`)
- Suwak progu przesunięty na stronie po kalibracji → skalibrowane gesty tej sesji zostają, reszta gestów i inne sesje biorą nową wartość. (Task 4: `test_slider_after_calibration_keeps_session_overrides`)
- Brak `say` (Windows, Linux) albo brak głosu Zosia → kalibracja idzie dalej, kroki widać na stronie. (Task 3: `test_voice_without_say_is_silent`, `test_voice_falls_back_to_default_voice`)

---

### Task 1: Ustawienia, głowa zawsze z żyroskopu, wyciszanie twarzy przy ruchu głowy

**Files:**
- Modify: `backend/settings.py`, `backend/headgyro.py`, `backend/sessions.py` (`EegPipeline`, `EegSession.__init__`, `Hub.apply_settings`)
- Test: `backend/tests/test_settings.py`, `backend/tests/test_headgyro.py`, `backend/tests/test_sessions.py`

**Interfaces:**
- Produces:
  - ustawienia: `calibration: bool = True`, `voice: bool = True`, `record: bool = True`, `motion_mute_s: float = 1.5` (zakres 0–5; 0 = wyłączone), `motion_mute_dps: float = 30.0` (10–200), `head_gyro_dps` bez zmian; brak `head_gyro`.
  - `HeadGyro.vmax: np.ndarray (2,)`, `HeadGyro.vmin: np.ndarray (2,)` — największa i najmniejsza prędkość [obrót, pochylenie] (po odjęciu tła) w ostatnim `push()`; zera przed końcem rozgrzewki.
  - `EegPipeline(names, fs, bundle, thresholds, refractory_s=None, head_gyro_dps=DEFAULT_DPS, motion_mute_s=1.5, motion_mute_dps=30.0)`; `set_head(threshold_dps: float)`; `set_motion_mute(seconds: float, dps: float)`; `pipeline.motion: dict` = `{"n": próbki ostatniego kawałka, "vmax": [..], "vmin": [..]}`; `pipeline.muted: int`.
  - wynik `process()`: zdarzenie twarzy/oczu wyciszone ma `event = None` i `muted = "<gest>"`.

- [ ] **Step 1: testy ustawień** — `test_defaults_calibration_fields` (wartości jak wyżej, `"head_gyro" not in d`), `test_old_file_with_head_gyro_loads` (`validate({"head_gyro": False}, d)` nie rzuca, wynik bez `head_gyro`), `test_new_fields_validated` (złe: `{"calibration": "yes"}`, `{"motion_mute_s": 9}`, `{"motion_mute_dps": 5}`, `{"record": 1}` → `ValueError`). Usunąć asercje o `head_gyro` z istniejących testów.
- [ ] **Step 2: testy potoku** —
  - `test_model_head_events_always_dropped`: `pl.gr` podmienione atrapą zwracającą `{"event": "head_left", "probs": {...}}` → `process()` daje `event is None`.
  - `test_face_muted_after_head_motion`: kawałek z `Gyro_y = 80°/s` (po rozgrzewce żyroskopu), potem atrapa zgłasza `jaw` w ciągu 1,5 s → `event is None`, `muted == "jaw"`, `pl.muted == 1`; ten sam `jaw` po 2 s spokoju → `event == "jaw"`.
  - `test_motion_mute_zero_disables`: `motion_mute_s=0` → `jaw` przechodzi mimo ruchu.
  - `test_gyro_event_not_muted`: `head_left` z żyroskopu przechodzi w trakcie ruchu.
  - zastąpić `test_pipeline_gyro_off_uses_model` i fragment `head_gyro=False` w `test_apply_settings_updates_gyro`; `test_apply_settings_updates_motion_mute`.
- [ ] **Step 3:** uruchomić testy — nowe nie przechodzą.
- [ ] **Step 4: implementacja.** Wyciszenie liczone w próbkach potoku (licznik `n_samples` rośnie o długość kawałka; `GestureRecognizer.t` zeruje się po `reset()`, więc nie nadaje się do porównań): `last_motion_n` = licznik po ostatnim kawałku, w którym `max(|vmax|, |vmin|) > motion_mute_dps`; zdarzenie modelu spoza `HEAD_GESTURES` jest wyciszane, gdy `(n_samples − last_motion_n) / fs <= motion_mute_s`. Żyroskop liczony przed decyzją o zdarzeniach modelu, żeby ruch z tego samego pakietu też wyciszał.
- [ ] **Step 5:** testy przechodzą.

### Task 2: Logika kalibracji

**Files:**
- Create: `backend/calibration.py`
- Test: `backend/tests/test_calibration.py`

**Interfaces:**
- Produces:
  - `FACE = ("blink", "jaw", "frown")`, `REST_S = 8.0`, `HEAD_S = 3.0`, `FACE_S = 2.5`, `FACE_REPEATS = 3`, `PEAK_FRACTION = 0.4`, `GYRO_LIMITS = (25.0, 120.0)`, `FACE_LIMITS = (0.15, 0.95)`, `MIN_GAIN = 0.08`, `MIN_HEAD_MOVES = 3`, `DISABLED = 2.0` (próg, którego pewność nie osiągnie).
  - `@dataclass Step(key: str, kind: str ("rest"|"head"|"face"), gesture: str | None, seconds: float, say: str, title: str, hint: str)`; `plan() -> list[Step]` — 1 + 4 + 9 kroków, razem 42,5 s.
  - `class Calibration(fs: float, warmup_s: float)`: `state` (`"waiting"|"running"|"done"|"skipped"`), `start() -> Step`, `feed(n: int, vmax, vmin, outs: list[dict]) -> list[Step]` (kroki rozpoczęte w tym wywołaniu; pusta lista zwykle; po ostatnim kroku `state == "done"` i gotowy `result`), `skip()`, `snapshot() -> dict` (`state, step, steps, title, hint, kind, gesture, progress, remaining_s, result`).
  - `result: dict` = `{"head_dps": float | None, "head_peaks": {gest: °/s}, "gestures": {g: {"threshold": float | None, "background": float, "peak": float, "hits": int, "trials": int, "works": bool | None}}}`; `None` = brak danych, zostaje próg globalny.
  - `Calibration.thresholds() -> dict[str, float]` — nadpisania dla sesji: próg dla działających, `DISABLED` dla niedziałających, bez gestów z `works is None`.
- [ ] **Step 1: testy** —
  - `test_plan_matches_spec`: kolejność `rest, head_left, head_right, head_up, head_down, blink, jaw, frown, blink, …`; czasy 8 / 3 / 2,5; suma 42,5.
  - `test_steps_advance_by_samples`: `feed` po 5 próbek przy 250 Hz → drugi krok zaczyna się dokładnie po 2000 próbkach, `done` po 10 625.
  - `test_gyro_threshold_from_peaks`: szczyty 100, 120, 80, 140 → `0.4 × 110 = 44.0`; szczyty po 400 → `120.0`; szczyty po 40 → `25.0`.
  - `test_gyro_too_few_moves_keeps_global`: dwa ruchy powyżej 25°/s, dwa poniżej → `head_dps is None`. Ruch w złą stronę (ujemna prędkość w kroku „w lewo”) się nie liczy.
  - `test_face_threshold_formula`: tło 0,10 (kwantyl 0,95 z kroku spokoju i kroków innych gestów), maksima w krokach gestu 0,80 / 0,70 / 0,90 → `0.10 + 0.4 × 0.70 = 0.38`, `works is True`, `hits == 3`.
  - `test_face_limits`: wynik poniżej 0,15 → 0,15; powyżej 0,95 → 0,95.
  - `test_face_not_working_is_disabled`: szczyt ≤ tło + 0,08 albo tylko 1 z 3 prób ponad progiem → `works is False`, `thresholds()[g] == DISABLED`.
  - `test_face_without_contact_keeps_global`: okna z `contact_ok False` pomijane; mniej niż 2 próby z danymi → `works is None`, gestu nie ma w `thresholds()`.
  - `test_warmup_windows_ignored`: okna z `t < warmup_s` nie wchodzą do tła.
  - `test_skip`: `skip()` → `state == "skipped"`, `thresholds() == {}`, kolejne `feed` nic nie robi.
- [ ] **Step 2:** testy nie przechodzą. **Step 3:** implementacja. **Step 4:** testy przechodzą.

### Task 3: Głos i zapis sesji

**Files:**
- Create: `backend/voice.py`, `backend/recording.py`
- Modify: `.gitignore` (`backend/recordings/`)
- Test: `backend/tests/test_voice.py`, `backend/tests/test_recording.py`

**Interfaces:**
- Produces:
  - `class Voice(which=shutil.which, run=subprocess)`: `available: bool`; `say(text: str) -> None` (nie blokuje; przerywa poprzednią wypowiedź; `say -v Zosia`, a gdy głosu nie ma na liście `say -v ?` — głos domyślny; bez `say` nic nie robi); `stop()`.
  - `class SessionRecording(root: Path, hello: Hello, started: float)`: katalog `<root>/<RRRR-MM-DD_GGMMSS>_P<gracz>_<nazwa opaski>/`; `add_packet(p: Packet, arrival_unix: float)` → `eeg.csv` z nagłówkiem `sample,t_s,arrival_unix,<kanały>,contact_<kanały>,Accel_x..z,Gyro_x..z,Sample` (kolumny jak w `tools/training/sessions/*/eeg.csv`; `Sample` = numer próbki telefonu; wiersze dummy pomijane); `add_event(event: str, label: str | None = None, details: dict | None = None)` → `events.csv` (`sample,t_s,unix_time,event,label,details`); `close()` zapisuje `session.json` (`format: "halo-arcade-recording/1"`, gracz, opaska, fs, kanały, liczba próbek, czas). `path: Path`, `rows: int`.
- [ ] **Step 1: testy** — `test_voice_uses_zosia`, `test_voice_falls_back_to_default_voice`, `test_voice_without_say_is_silent`, `test_voice_interrupts_previous`; `test_recording_rows_and_header` (2 pakiety po 5 próbek, 1 wiersz dummy → 9 wierszy, `Sample` zgodny z telefonem), `test_recording_events_use_row_index`, `test_recording_close_writes_meta`, `test_recording_name_is_safe` (nazwa opaski ze znakami `/` i spacją).
- [ ] **Step 2:** nie przechodzą. **Step 3:** implementacja. **Step 4:** przechodzą.

### Task 4: Sesja, kolejka kalibracji, API

**Files:**
- Modify: `backend/sessions.py` (`EegSession`, `Hub`), `backend/app.py`
- Test: `backend/tests/test_sessions.py`, `backend/tests/test_app.py`, `backend/tests/test_e2e.py`

**Interfaces:**
- Consumes: `Calibration`, `Voice`, `SessionRecording`, `EegPipeline.motion`.
- Produces:
  - `Hub(settings, arcade, bundle, voice=None, recordings_dir=None)`; `Hub.calibration_turn(session) -> bool` (jedna kalibracja naraz, kolejność zgłoszeń), `Hub.calibration_release(session)`.
  - `EegSession.cal: Calibration | None`; `EegSession.recalibrate()`, `EegSession.skip_calibration()`, `EegSession.close()`; migawka sesji: `calibration` (z `Calibration.snapshot()` albo `None`), `thresholds` (progi tej sesji), `head_dps`, `muted`, `recording` (nazwa katalogu albo `None`).
  - `create_app(..., recordings_dir=HERE / "recordings", voice=None)`; `POST /api/calibration {"player": 1, "action": "skip" | "restart"}` → 200 z migawką kalibracji; 400 zła akcja/gracz; 409 gdy gracz nie ma sesji EEG.
- Zachowanie: w stanach `waiting` i `running` gesty nie idą do `hub.dispatch` (licznik `stats["held"]`); po `done` progi sesji = globalne nadpisane wynikiem, próg żyroskopu = wynik albo globalny; po `skipped` globalne. `apply_settings` zachowuje nadpisania sesji. Polecenia głosowe: krok → `step.say` (pierwszy krok z numerem gracza), koniec → „Gotowe.” i nazwy wyłączonych gestów; tylko gdy `voice` w ustawieniach. Zdarzenia w nagraniu: `calibration_step`, `calibration_done`, `calibration_skipped`, `gesture` (z przyciskiem i `via`), `muted`, `reset`.
- [ ] **Step 1: testy** (atrapa potoku z `motion`, atrapa głosu zbierająca teksty) —
  - `test_no_dispatch_during_calibration`, `test_calibration_done_applies_thresholds_and_head_dps`, `test_calibration_off_dispatches_immediately`, `test_voice_prompts_in_order`, `test_voice_setting_off_is_silent`,
  - `test_two_players_calibrate_one_after_another`, `test_disconnect_during_calibration_releases_turn`,
  - `test_skip_uses_global_thresholds`, `test_restart_runs_again`, `test_slider_after_calibration_keeps_session_overrides`,
  - `test_recording_created_and_closed` (ustawienie `record` wyłączone → brak katalogu),
  - `test_api_calibration_skip`, `test_api_calibration_without_session_409`, `test_api_calibration_bad_action_400`,
  - istniejące testy wysyłania gestów: ustawienie `calibration` wyłączone w ich `store`; `test_e2e` — kalibracja wyłączona w jednym przebiegu i jeden nowy przebieg z kalibracją pomijaną przez API.
- [ ] **Step 2:** nie przechodzą. **Step 3:** implementacja. **Step 4:** cały zestaw `backend/tests` przechodzi.

### Task 5: Strona ustawień i README

**Files:**
- Modify: `backend/static/index.html`, `backend/README.md`

- [ ] **Step 1: strona.** Zamiast pola wyboru żyroskopu: suwak progu żyroskopu (zawsze aktywny), pola „Kalibracja na starcie sesji”, „Polecenia głosem”, „Zapis sesji na dysk”, suwaki wyciszania (czas 0–5 s co 0,1; prędkość 10–100°/s co 5). Ekran gracza w kalibracji: nazwa kroku dużą czcionką, podpowiedź, pasek postępu, pozostały czas; po kalibracji wiersz z progiem głowy i progami/wyłączeniami gestów twarzy. Przycisk „Pomiń” / „Kalibruj ponownie” w górnej belce ekranu gracza (poza obszarem przerysowywanym 5 razy na sekundę, żeby kliknięcie nie ginęło). Czerwone kreski progów z `p.thresholds`. Wiersze głowy w tabeli zawsze „z żyroskopu”.
- [ ] **Step 2: próba na żywo bez ruszania portu 8000:** drugi serwer na porcie 8011 z ustawieniami w katalogu tymczasowym i głosem wyłączonym, `python -m backend.sim_phone` z nagraniem sesji głowy; w przeglądarce widać kroki kalibracji, „Pomiń” i „Kalibruj ponownie” działają, po kalibracji gesty głowy trafiają do logu; w katalogu nagrań powstaje sesja. Jedna próba z głosem (krótki krok), żeby usłyszeć Zosię.
- [ ] **Step 3: README** — sekcje „Kalibracja”, „Wyciszanie przy ruchu głowy”, „Nagrania sesji” (miejsce, format, ok. 2 MB na minutę na gracza), nowe ustawienia, nowe API; usunąć opis przełącznika `head_gyro`.

## Po wdrożeniu

Działający serwer (port 8000) trzyma stary kod — nowe zachowanie zacznie działać po jego restarcie, o który trzeba zapytać użytkownika (restart przerywa grę na kilka sekund).
