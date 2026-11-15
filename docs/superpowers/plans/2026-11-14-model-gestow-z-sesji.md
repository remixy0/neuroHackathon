# Model gestów z sesji treningowych — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Z nagrań `tools/training/sessions/` wytrenować model gestów zgodny z aplikacją, zmierzyć jego dokładność i zapisywać historię wyników przy każdym kolejnym treningu.

**Architecture:** Nowy loader sesji → wykrycie początku ruchu po każdym sygnale → okna 1,5 s z istniejących cech przyczynowych (`gestures/features.py`, te same co na żywo) → normalizacja do tła sesji → klasyfikator sklearn wybrany walidacją → progi klas z osób spoza treningu. Format modelu (`gestures.model.make_bundle`) i `GestureRecognizer` zostają, więc aplikacja czyta model bez zmian.

**Tech Stack:** Python 3.13 (`tools/.venv`), numpy, scipy, scikit-learn, joblib; testy `unittest` (bez nowych zależności).

**Spec:** `docs/superpowers/specs/2026-11-14-model-gestow-z-sesji-design.md`

## Global Constraints

- Klasy i ich kolejność: `gestures.data.CLASSES` (10 klas) — bez zmian.
- Model w obiekcie zapisu to wyłącznie klasy sklearn (działający silnik ma stary kod w pamięci i musi go odczytać).
- `MODEL_VERSION` i `feature_names()` zmieniamy tylko, gdy walidacja pokaże wyraźny zysk; wtedy aplikacja wymaga restartu.
- Trening zapisuje do `models/gestures_candidate.joblib`. `models/gestures.joblib` tylko z flagą `--install`, po zgodzie użytkownika.
- Okna jednej próby nigdy po obu stronach podziału walidacji.
- Bez commitów (użytkownik o nie nie prosił; w repo są jego niezatwierdzone zmiany).
- Komentarze i komunikaty po polsku bez znaków diakrytycznych, jak w istniejącym kodzie.

## Review Focus

1. Sesja `demo: true`, `status != complete` lub bez `intervals.csv` → pominięta z powodem, trening idzie dalej.
2. Sesja z martwym kanałem / bez kontaktu elektrod → pominięta (`quality_problems`), z powodem w raporcie.
3. Osoba bez którejś klasy (Stas bez głowy) albo klasa tylko u jednej osoby → walidacja nie pada, metryka klasy = brak danych.
4. Próba za blisko początku/końca nagrania (brak 1,5 s okna + rozruch filtrów) → pominięta, nie wyjątek.
5. Uszkodzony / stary `gestures_report.json` → historia zaczyna się od nowa, trening nie pada.

---

### Task 1: Loader sesji

**Files:** Create `tools/gestures/sessions.py`, `tools/tests/__init__.py`, `tools/tests/synth.py`, `tools/tests/test_sessions.py`

**Interfaces — Produces:**
- `SESSIONS_DIR: Path` (= `TRAIN_DIR / "sessions"`)
- `@dataclass Session`: `id, person, mode, device: str; fs: float; channels: list[str]; x: np.ndarray (kanaly x probki, bez kolumn sample/t_s/arrival_unix); events: list[dict]; intervals: list[dict]` (liczby w `intervals` jako int/float, puste pola = None)
- `load_session(d: Path) -> Session`
- `load_sessions(root=SESSIONS_DIR) -> tuple[list[Session], list[tuple[str, str]]]` — (wczytane, [(id, powod pominiecia)])
- `tests/synth.py`: `write_session(root, sid, person, mode, trials, *, seed=0, demo=False, status="complete", dead=False) -> Path` — syntetyczna sesja w formacie `braingestures-session/1` z wyraźnymi ruchami (impuls żyroskopu dla głowy, wychylenie Fp dla mrugnięcia, szum 30–110 Hz dla czoła/szczęki, skok Fp1−Fp2 dla oczu) 0,35 s po sygnale.

- [ ] Testy: wczytanie syntetycznej sesji (kształt `x`, kanały, etykiety interwałów); `demo`, `status="aborted"`, brak `intervals.csv`, martwy kanał → w liście pominiętych z powodem (Review Focus 1, 2).
- [ ] Implementacja, testy zielone: `.venv/bin/python -m unittest tests.test_sessions -v`

### Task 2: Początek ruchu

**Files:** Create `tools/gestures/onsets.py`, `tools/tests/test_onsets.py`

**Interfaces — Produces:** `detect_onset(sig: dict[str, np.ndarray], label: str, cue: int, limit: int, fs: float) -> tuple[int, bool]` — (próbka początku ruchu, `weak`). `sig` = wynik `features.filter_all`. Szuka w `[cue + 0.1 s, min(limit, cue + 1.5 s)]`: głowa — pierwsze przekroczenie progu prędkości kątowej; mrugnięcie/oczy — wychylenie Fp (EOG); czoło/szczęka — wzrost obwiedni EMG; próg względem odcinka przed sygnałem. Brak przekroczenia → `(cue + 0.35 s, True)`.

- [ ] Testy na syntetycznych sesjach: wykryty początek w ±0,15 s od wstrzykniętego dla każdej rodziny; sygnał bez ruchu → `weak=True` i `cue + 0.35 s`.
- [ ] Implementacja, testy zielone.

### Task 3: Okna z sesji

**Files:** Create `tools/gestures/session_windows.py`, `tools/tests/test_windows.py`; Modify `tools/gestures/dataset.py` (`Windows` + pola `session`, `weak`), `tools/gestures/model.py` (tło liczone per sesja, gdy `W.session` jest)

**Interfaces — Produces:**
- `Windows.session: np.ndarray | None`, `Windows.weak: np.ndarray | None` (propagowane w `__getitem__`)
- `session_rows(s: Session) -> list[tuple[np.ndarray, str, str, int, bool]]` — (cechy, etykieta, rodzaj, nr próby w sesji, weak). Rodzaje: `event` (okna kończące się `EVENT_OFFSETS` po początku ruchu), `hold` (czoło/szczęka: trzymanie do sygnału powrotu), `rest` (baseline, kawałki 2,5 s, nr próby ujemny), `quiet` (tuż przed sygnałem, bez ruchu głowy), `moving` (przed sygnałem, z ruchem — waga 0).
- `build(sessions: list[Session]) -> Windows` — `trial` globalnie unikalny.
- Interwały `center`, `pursuit` i ruchy powrotne nie dają okien.

- [ ] Testy: etykiety i rodzaje okien per tryb; `trial` unikalny między sesjami; próba przy krawędzi nagrania pominięta (Review Focus 4); `normalize_windows` odejmuje tło własnej sesji.
- [ ] Implementacja, testy zielone.

### Task 4: Walidacja i raport

**Files:** Create `tools/gestures/validation.py`, `tools/gestures/report.py`, `tools/tests/test_validation.py`, `tools/tests/test_report.py`

**Interfaces — Produces:**
- `folds(W, how: str) -> np.ndarray` — numer części dla każdego okna; `how` ∈ `person`, `session`, `block` (5 kolejnych bloków prób w każdej sesji).
- `cv_proba(W, fold: np.ndarray) -> np.ndarray` — prawdopodobieństwa z modeli, które nie widziały części okna.
- `window_metrics(W, P) -> dict` — `accuracy`, `balanced_accuracy`, `per_class {recall, precision, n}`, `confusion`, `false_alarm_rate` (okna tła uznane za gest). Klasa bez okien → `None` (Review Focus 3).
- `stream_metrics(sessions, bundles_by_person) -> dict` — symulacja na żywo `GestureRecognizer.run` na całych sesjach modelem bez tej osoby: `per_class {hit_rate, n}`, `wrong_gesture`, `false_per_min` (poza próbami), per etykieta.
- `report.update(path, entry: dict) -> dict` — zapisuje `{"latest": entry, "history": [...]}`; uszkodzony plik → nowa historia (Review Focus 5).

- [ ] Testy: brak przecieku (żadna próba po obu stronach, dla każdego `how`); metryki na ręcznie policzonym przykładzie; klasa nieobecna u osoby; `report.update` dopisuje i przeżywa zepsuty plik.
- [ ] Implementacja, testy zielone.

### Task 5: Wybór modelu na prawdziwych danych

**Files:** Modify `tools/gestures/model.py` (`new_classifier`, wagi okien, progi, klasy niepewne), ewentualnie `tools/gestures/features.py`

- [ ] Uruchomić walidację „nowa osoba" dla kandydatów (RandomForest, ExtraTrees, HistGradientBoosting, regresja logistyczna) oraz wariantów wag (`hold`, `quiet`, próby `weak`). Wybrać po `balanced_accuracy` i fałszywych alarmach; decyzję i liczby zapisać w komentarzu przy `new_classifier`.
- [ ] Progi: kwantyl 0,99 w oknach tła osób spoza treningu; klasa z trafnością prób < 30% u nowych osób → `bundle["unreliable"]`, próg 0,95.
- [ ] `selftest` (cechy strumieniowe == treningowe, `push() == run()`) przepisany na sesje i zielony.

### Task 6: Skrypty i dokumentacja

**Files:** Rewrite `tools/train_gestures.py`, `tools/evaluate_gestures.py`; Modify `tools/gestures/selftest.py`, `tools/README.md`, `tools/training/README.md` nie ruszamy (generuje go aplikacja)

- [ ] `train_gestures.py [--out PATH] [--install] [--no-eval]`: wczytuje wszystkie sesje, wypisuje pominięte, trenuje, liczy walidację, zapisuje model + `models/gestures_report.json` (z historią: data, liczba sesji/osób/okien, metryki), wypisuje porównanie z poprzednim treningiem i wskazówkę, czego nagrać więcej (najsłabsze klasy, osoby bez danej klasy).
- [ ] `evaluate_gestures.py [--how person|session|block|all] [--stream]`: tylko pomiar, bez zapisu modelu.
- [ ] README: jak dołożyć dane i wytrenować ponownie, jak czytać raport.
- [ ] Weryfikacja end-to-end: trening na 25 sesjach, model wczytany przez `gm.load`, `GestureRecognizer.run` na jednej sesji, wszystkie testy zielone.
