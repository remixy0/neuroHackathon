# NeuroHackathon – sterowanie grami gestami z opaski EEG

Opaska BrainAccess HALO wysyła sygnał do telefonu, telefon do backendu, backend rozpoznaje gesty
(ruchy głowy, szczęka, czoło) i naciska przyciski w grach Arcade (Tetris, Pong, Runner).

```text
HALO ──BLE── telefon ──WebSocket── backend :8000 (model gestów) ──WebSocket── frontend Arcade :5173 / :8787
```

| Folder | Co to jest | Windows | macOS / Linux |
|---|---|---|---|
| `arcade/` | **frontend**: gry w przeglądarce + serwer sterowania (Node.js, Vite) | tak | tak |
| `backend/` | **backend**: serwer FastAPI z modelem gestów i stroną ustawień | tak | tak |
| `tools/` | trening i ocena modelu gestów (Python) | tak (trening z nagranych sesji) | tak |
| `macos/` | aplikacja BrainGestures do nagrywania sesji treningowych (SwiftUI) | **nie** | tylko macOS |

Do grania wystarczą `arcade/` i `backend/`. Szczegóły każdej części: `arcade/README.md`, `backend/README.md`,
`tools/README.md`, `macos/README.md`.

## Wymagania

- **Node.js 20.19 lub nowszy** (frontend),
- **Python 3.13** (backend),
- plik modelu `tools/models/gestures.joblib` (patrz [Model gestów](#model-gestów) – nie ma go w repozytorium).

## Frontend (Arcade)

Tak samo na Windows, macOS i Linuksie:

```bash
cd arcade
```

```bash
npm install
```

```bash
npm run dev
```

Gra działa pod adresem wypisanym przez Vite (zwykle http://localhost:5173). Razem z nią startuje serwer
sterowania na portach 8787 (WebSocket i HTTP) oraz 8788 (UDP). `npm install` wystarczy zrobić raz.

Frontend działa też sam, bez backendu: klawiatura, gamepad albo pad na telefonie (`http://<IP komputera>:8787/?player=1`).

## Backend

Uruchamiaj z głównego folderu repozytorium, w drugim terminalu (frontend ma już działać).

### Windows

Raz, żeby utworzyć środowisko i zainstalować paczki:

```bat
backend\run.bat --install
```

Start serwera:

```bat
backend\run.bat
```

To samo ręcznie, bez skryptu:

```bat
py -3.13 -m venv backend\.venv
```

```bat
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
```

```bat
backend\.venv\Scripts\python -m backend
```

### macOS / Linux

```bash
./backend/run.sh --install
```

```bash
./backend/run.sh
```

### Po starcie

- Strona ustawień gestów: http://localhost:8000/
- Serwer wypisuje adres dla telefonu, np. `ws://192.168.1.20:8000/ws/controller`. Wpisz go w aplikacji
  HALO Controller. Telefon i komputer muszą być w tej samej sieci.
- Backend sam łączy się z Arcade pod `ws://localhost:8787`.
- Okno gry musi być widoczne na ekranie (przeglądarka wstrzymuje grę w ukrytej karcie).

Port zmienisz zmienną `PORT` albo opcją `--port`, np. `backend\run.bat --port 8001`.

### Bez opaski i bez telefonu

Najprościej: na stronie http://localhost:8000/ przyciski „Gracz 1 / Gracz 2” wysyłają gest do gry.

Pad wpisywany w terminalu (`left`, `a`, `start`…):

```bat
backend\.venv\Scripts\python -m backend.sim_phone --manual --player 1
```

Na macOS / Linuksie zamiast `backend\.venv\Scripts\python` wpisz `backend/.venv/bin/python`.
Odtwarzanie nagranej sesji (`python -m backend.sim_phone --player 1`) wymaga nagrań w `tools/training/sessions/`,
których nie ma w repozytorium.

## Model gestów

Backend nie wystartuje bez pliku `tools/models/gestures.joblib` (ok. 50 MB). Plik jest w `.gitignore`,
więc po `git clone` go nie ma. Dwa sposoby:

1. **Skopiuj plik** z komputera, na którym model powstał, do `tools/models/gestures.joblib`.
   Wersje `numpy`, `scipy`, `scikit-learn` i `joblib` są przypięte w `backend/requirements.txt`, żeby model
   wczytywał się tak samo na każdym systemie.
2. **Wytrenuj model** – potrzebne są nagrane sesje w `tools/training/sessions/` (też tylko lokalnie, trzeba je skopiować):

   ```bat
   cd tools
   ```

   ```bat
   ..\backend\.venv\Scripts\python train_gestures.py
   ```

## Windows – na co uważać

- **Zapora**: przy pierwszym starcie Windows zapyta o dostęp do sieci dla Node.js i Pythona. Zezwól w sieci
  prywatnej, inaczej telefon nie połączy się z komputerem.
- **Python**: skrypt używa `py -3.13`. Gdy nie masz programu `py`, zainstaluj Pythona 3.13 z python.org
  (z zaznaczonym „Add python.exe to PATH”).
- **PowerShell** uruchamia skrypt tak samo: `backend\run.bat`. Zmienne środowiskowe ustawiasz przez
  `$env:PORT="8001"`, w cmd przez `set PORT=8001`.
- **Aplikacja `macos/`** nie działa na Windows. Nowe sesje treningowe nagrasz tylko na Macu; granie i trening
  modelu z gotowych sesji działają na Windows.
- Starsze skrypty w `tools/` (`live.py`, `record_cues.py`, `train.py`…) pracują na archiwalnych danych
  i nie były sprawdzane na Windows.

## Testy

Frontend:

```bash
cd arcade
```

```bash
npm test
```

Backend (Windows; na macOS / Linuksie `backend/.venv/bin/python`):

```bat
backend\.venv\Scripts\python -m pytest backend\tests -q
```

Testy backendu wymagają pliku modelu (bez niego kończą się błędem). Testy na nagranych sesjach są
pomijane, gdy nagrań nie ma.
