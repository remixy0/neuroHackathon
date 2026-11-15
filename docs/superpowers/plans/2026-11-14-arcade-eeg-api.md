# HALO → Arcade (FastAPI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serwer FastAPI przyjmujący telefony wg WEBSOCKET.md v1, rozpoznający gesty modelem `tools/models/gestures.joblib` i wysyłający zmapowane przyciski do Arcade, ze stroną ustawień.

**Architecture:** Pakiet `backend/` uruchamiany `python -m backend`. Czysta walidacja protokołu (`protocol.py`), ustawienia/mapowanie (`settings.py`), klient WebSocket do Arcade (`arcade.py`), sesje i rozpoznawanie w wątku (`sessions.py`), FastAPI (`app.py`), strona `static/index.html`.

**Tech Stack:** Python 3.13, FastAPI, uvicorn[standard], websockets, numpy 2.5.4, scipy 1.18.1, scikit-learn 1.9.1, joblib 1.6.0, pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-11-14-arcade-eeg-api-design.md` (+ kontrakt `~/Downloads/WEBSOCKET.md`)

## Global Constraints

- Model tylko czytany: nigdy nie zapisywać `tools/models/gestures.joblib`, nie ruszać `tools/.venv`, `macos/`, kodu Arcade.
- Własne środowisko `backend/.venv` (python3.13) z wersjami numpy/scipy/scikit-learn/joblib jak wyżej.
- Serwer: `0.0.0.0`, port `PORT` (domyślnie 8000); ping uvicorna co 5 s, limit 10 s; wiadomość telefonu maks. 1 MiB.
- Arcade domyślnie `ws://localhost:8787`; przycisk = `{"player":P,"button":B,"ms":MS,"id":ID}`.
- Przyciski: `up down left right a b x select start`; gesty: `head_left head_right head_up head_down jaw frown blink look_left look_right`; profile: `menu tetris pong runner`.
- Bez commitów (repo użytkownika ma niezacommitowaną pracę; commit tylko na prośbę).
- Testy: `backend/.venv/bin/python -m pytest backend/tests -q` z katalogu repo.

## Review Focus

- Arcade wyłączony przy starcie albo zrestartowany w trakcie gry → serwer ponawia połączenie, gesty w tym czasie są tylko logowane („offline”), nie kolejkowane. (Task 3: `test_press_offline_returns_false`)
- Pakiet z wierszami `is_dummy` albo przeskokiem `first_sample_index` → reset rozpoznawania, bez wyjątku i bez gestów z wierszy dummy. (Task 4: `test_dummy_rows_dropped_and_reset`, `test_index_gap_resets`)
- Uszkodzony / stary `settings.json` (brak pól, nieznany gest/przycisk) → domyślne wartości uzupełnione, PUT ze złymi danymi → 400 bez zmiany pliku. (Task 2: `test_load_corrupt_file_falls_back`, Task 5: `test_put_settings_invalid_400`)
- Ekran ustawień gry w Arcade (`screen:"setup"`, `game:"tetris"`) → profil `menu`, a nie `tetris`. (Task 2: `test_profile_for_setup_is_menu`)
- Opóźnione zamknięcie starego socketu po reconnect nie zwalnia gracza nowej sesji. (Task 4: `test_release_only_by_owner`)

---

### Task 1: Środowisko + walidacja protokołu

**Files:**
- Create: `backend/__init__.py`, `backend/requirements.txt`, `backend/protocol.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_protocol.py`

**Interfaces:**
- Produces:
  - `class ProtocolError(Exception)` z polami `code: str`, `message: str`
  - `BUTTONS: tuple[str,...]`, `EEG_REQUIRED = ("O1","O2","Fp2","Fp1")`, `MAX_MESSAGE = 1 << 20`
  - `@dataclass Hello(session_id: str, player: int, mode: str, channels: list[str], fs: float, device: dict)`
  - `@dataclass Packet(seq: int, n: int, first_index: int, eeg: np.ndarray (N,C), accel: np.ndarray (N,3), gyro: np.ndarray (N,3), dummy: np.ndarray[bool] (N,), contact: list[bool], battery: float|None)`
  - `@dataclass Press(seq: int, id: str, button: str)`
  - `parse_json(text: str) -> dict` (zły JSON/nie obiekt → `invalid_packet`; brak `type` → `invalid_packet`; `version != 1` → `unsupported_version`)
  - `parse_hello(msg: dict) -> Hello`
  - `parse_samples(msg: dict, hello: Hello, expected_seq: int) -> Packet`
  - `parse_manual(msg: dict, hello: Hello, expected_seq: int) -> Press`
  - `encode(type_: str, session_id: str, **fields) -> str` (dodaje `version: 1`)

- [ ] **Step 1:** `python3.13 -m venv backend/.venv`, `requirements.txt` (fastapi, uvicorn[standard], websockets, httpx, pytest, numpy==2.5.4, scipy==1.18.1, scikit-learn==1.9.1, joblib==1.6.0), instalacja. `conftest.py` dodaje katalog repo do `sys.path`.
- [ ] **Step 2: testy** `test_protocol.py`:
  - `test_hello_eeg_ok` → `Hello.mode == "eeg"`, `fs == 250`, kanały z wiadomości.
  - `test_hello_manual_ok` (`mode:"manual"`, bez `device`/`stream`).
  - `test_hello_rejects_v1_without_imu` (`has_gyro: false`) → `code == "unsupported_stream"`; `test_hello_rejects_missing_channel`, `test_hello_rejects_fs_500`, `test_hello_bad_player` (3) → `invalid_packet`, `test_hello_bad_uuid`.
  - `test_parse_json_bad_version` → `unsupported_version`; `test_parse_json_garbage` → `invalid_packet`.
  - `test_samples_ok`: przykład z kontraktu (2 próbki × 4 kanały) → `eeg.shape == (2,4)`, `accel[0].tolist() == [0.1,0.2,9.81]`, `first_index == 250`.
  - `test_samples_wrong_seq`, `test_samples_eeg_len_mismatch`, `test_samples_nan` (`"NaN"` / string w eeg), `test_samples_first_index_not_string`, `test_samples_contact_len` → `invalid_packet`.
  - `test_manual_ok`, `test_manual_bad_id` (`id` ≠ `"<sid>:<seq>"`), `test_manual_wrong_player`, `test_manual_bad_button` (`"y"`), `test_manual_action_not_press` → `invalid_packet`.
- [ ] **Step 3:** Uruchomić → FAIL (brak modułu). Zaimplementować `protocol.py`. Uruchomić → PASS.

### Task 2: Ustawienia i mapowanie

**Files:**
- Create: `backend/settings.py`
- Test: `backend/tests/test_settings.py`

**Interfaces:**
- Produces:
  - `GESTURES: list[str]`, `PROFILES = ["menu","tetris","pong","runner"]`, `GESTURE_PL: dict[str,str]`
  - `profile_for(state: dict|None) -> str` — `"menu"`, gdy brak stanu, `screen != "game"` albo gra spoza profili.
  - `default_settings(model_thresholds: dict[str,float]) -> dict` → `{"arcade_url": str, "thresholds": {gest: float}, "profiles": {profil: {gest: {"button": str|None, "ms": int}}}}`; domyślne mapowania wg specu (Tetris `head_down` → `down` 400 ms, Pong head up/down 300 ms, reszta 120 ms).
  - `validate(data: dict, defaults: dict) -> dict` — uzupełnia braki z `defaults`, `ValueError` dla nieznanego gestu/profilu/przycisku, `ms` poza 30–2000, progu poza 0.05–0.99, URL nie `ws://`/`wss://`.
  - `class SettingsStore(path: Path, model_thresholds: dict)`: `.data: dict`, `.replace(new: dict) -> dict` (walidacja + zapis atomowy), `.action(profile: str, gesture: str) -> tuple[str,int]|None`.
- [ ] **Step 1: testy:** `test_defaults_cover_all_profiles_and_gestures`, `test_profile_for_game` (`{"screen":"game","game":"pong"}` → `"pong"`), `test_profile_for_setup_is_menu`, `test_profile_for_none_is_menu`, `test_validate_rejects_unknown_button`, `test_validate_rejects_ms_out_of_range`, `test_replace_persists_and_reloads` (nowy `SettingsStore` na tym samym pliku widzi zmianę), `test_load_corrupt_file_falls_back` (plik `"{"` → domyślne), `test_action_none_when_unmapped` (`blink` w menu → `None`).
- [ ] **Step 2:** FAIL → implementacja → PASS.

### Task 3: Klient Arcade

**Files:**
- Create: `backend/arcade.py`
- Test: `backend/tests/test_arcade.py`

**Interfaces:**
- Produces: `class ArcadeLink(url: str)`: `async run()` (pętla połączeń, ponowienia 1→10 s), `set_url(url)` (zrywa bieżące połączenie), `connected: bool`, `state: dict|None` (ostatnia wiadomość `type:"state"`), `async press(player: int, button: str, ms: int, id: str) -> bool`, `async close()`.
- [ ] **Step 1: testy** (atrapa Arcade: `websockets.serve` na wolnym porcie):
  - `test_press_reaches_arcade` → atrapa dostaje `{"player":1,"button":"left","ms":120,"id":"x"}`.
  - `test_state_tracked` → atrapa wysyła `{"type":"state","game":"tetris","screen":"game"}` → `link.state["game"] == "tetris"`.
  - `test_press_offline_returns_false` (URL na zamknięty port).
  - `test_reconnects_after_server_restart`.
- [ ] **Step 2:** FAIL → implementacja (`websockets.asyncio.client.connect`) → PASS.

### Task 4: Sesje, rozpoznawanie, rejestr graczy

**Files:**
- Create: `backend/sessions.py`
- Test: `backend/tests/test_sessions.py`

**Interfaces:**
- Consumes: `Hello`, `Packet` (Task 1); `SettingsStore`, `profile_for` (Task 2); `ArcadeLink`-podobny obiekt z `press`/`state`/`connected` (Task 3).
- Produces:
  - `load_bundle(path: Path|None = None) -> dict` (importuje `tools/gestures`; ścieżka `tools` dopisana do `sys.path`).
  - `class PlayerRegistry`: `claim(player, owner) -> bool`, `release(player, owner) -> None` (tylko właściciel), `owner(player)`.
  - `packet_chunk(p: Packet, hello: Hello) -> tuple[list[str], np.ndarray]` — wiersze: kanały z `hello`, `contact_<kanał>` (kontakt pakietu powielony), `Accel_x..z`, `Gyro_x..z`; wiersze `dummy` usunięte.
  - `class EegPipeline(channels, fs, bundle, thresholds)`: `process(chunk) -> list[dict]` (wyjście `GestureRecognizer.push`), `reset()` (nowy rozpoznawacz, przeniesione `history` tła osoby), `set_thresholds(d)`.
  - `class Hub(settings: SettingsStore, arcade, bundle)`: `registry`, `sessions: dict[int, Session]`, `log: deque`, `async dispatch(player: int, gesture: str, confidence: float, source: str) -> dict` (profil z `arcade.state`, mapowanie, `arcade.press`, wpis w logu z `sent: bool` i `button`), `snapshot() -> dict` (dla `/ws/ui`).
  - `class EegSession`: `accept(packet, arrival: float) -> None` (do kolejki, limit 500 próbek → wyrzucenie starych + reset), `async worker(send_preview)`, `stats` (pakiety, ack, bateria, kontakt, rozgrzewka, ostatnie prawdopodobieństwa), `close()`. Reset przy: `first_index != poprzedni first_index + n`, dowolny `dummy`. Gest pomijany, gdy `time.monotonic() - arrival > 1.0`.
- [ ] **Step 1: testy:**
  - `test_registry_busy` (drugi `claim` → False), `test_release_only_by_owner`.
  - `test_packet_chunk_layout` → nazwy zawierają `contact_O1`, `Gyro_z`; kształt `(4+4+6, N)`.
  - `test_dummy_rows_dropped_and_reset` → chunk bez wierszy dummy i `pipeline.reset` wywołane.
  - `test_index_gap_resets`.
  - `test_pipeline_detects_head_gestures` → odtworzenie 60 s z `tools/training/sessions/*_head/eeg.csv` (najnowsza) pakietami po 10 próbek daje ≥ 3 zdarzenia `head_*`.
  - `test_dispatch_uses_game_profile` (atrapa arcade ze `state` Runnera: `jaw` → `a`), `test_dispatch_unmapped_logged_not_sent`, `test_stale_gesture_skipped`.
- [ ] **Step 2:** FAIL → implementacja → PASS.

### Task 5: Aplikacja FastAPI

**Files:**
- Create: `backend/app.py`, `backend/__main__.py`
- Test: `backend/tests/test_app.py`

**Interfaces:**
- Consumes: wszystko powyżej.
- Produces: `create_app(settings_path: Path, arcade=None, bundle=None, eeg_idle_s: float = 3.0, hello_timeout_s: float = 5.0, token: str|None = None) -> FastAPI`; endpointy `/ws/controller`, `/ws/ui`, `GET/PUT /api/settings`, `POST /api/test` `{player, gesture}`, `GET /api/info` (gesty z nazwą PL i skutecznością z `models/gestures_report.json` `live_new_person`, przyciski, profile, adresy LAN), `GET /` (strona). `__main__`: uvicorn z parametrami z Global Constraints.
- [ ] **Step 1: testy** (TestClient, atrapa arcade zapisująca `press`):
  - `test_manual_flow`: hello manual → `ready` z `mode:"manual"` → `manual` seq 0 → `ack` seq 0 i atrapa dostała `button:"left"`, `id == "<sid>:0"`.
  - `test_manual_duplicate_seq_error` → `error invalid_packet`, zamknięcie.
  - `test_player_busy` → drugi telefon na gracza 1 dostaje `error player_busy`.
  - `test_eeg_hello_ready_and_ack` → `ready` (bez `mode`), 3 pakiety → `ack` seq 2.
  - `test_samples_before_ready_not_possible / samples_in_manual_error`, `test_binary_frame_error`, `test_unknown_type_error`.
  - `test_eeg_idle_timeout_closes` (`eeg_idle_s=0.3`).
  - `test_token_required` (`token="t"`, bez nagłówka → odrzucenie upgrade).
  - `test_put_settings_invalid_400`, `test_put_settings_roundtrip`, `test_api_test_sends_mapped_button`.
- [ ] **Step 2:** FAIL → implementacja → PASS.

### Task 6: Strona ustawień

**Files:**
- Create: `backend/static/index.html`

**Interfaces:**
- Consumes: `/api/info`, `/api/settings` (GET/PUT), `/api/test`, `/ws/ui` (snapshot z Task 4).
- [ ] **Step 1:** Strona: pasek stanu (Arcade, gra/profil, adres telefonu, pole URL Arcade), karty graczy 1/2 (tryb, urządzenie, bateria, kontakt, pakiety, rozgrzewka, słupki prawdopodobieństw, ostatnie gesty), tabela mapowań (wiersz gest + skuteczność; kolumny profili: lista przycisków + ms; suwak progu; przyciski test P1/P2), log zdarzeń. Zmiana → PUT od razu. Ciemna, czytelna, styl Arcade; działa na telefonie.
- [ ] **Step 2:** Sprawdzić w przeglądarce (podgląd): ładuje się, zmiana mapowania zapisuje się do `settings.json`, „test” zapala zdarzenie w logu.

### Task 7: Atrapa telefonu + test końcowy + README

**Files:**
- Create: `backend/sim_phone.py`, `backend/README.md`, `backend/run.sh`

- [ ] **Step 1:** `sim_phone.py --player 1 [--csv ścieżka] [--speed 1] [--chunk 10] [--manual]` — EEG: hello wg kontraktu, odtwarzanie `eeg.csv` w czasie rzeczywistym, wypisuje ACK i podgląd `input`; manual: linie ze stdin (`left`, `a`…).
- [ ] **Step 2:** Uruchomić serwer + działające Arcade (8787) + `sim_phone.py` na sesji głowy → w logu serwera / na stronie widać gesty wysłane do Arcade; Arcade (strona gry) reaguje.
- [ ] **Step 3:** README: instalacja, uruchomienie, adres dla telefonu, strona ustawień, atrapa telefonu, ograniczenia modelu.
