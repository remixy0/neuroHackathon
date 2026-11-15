# Głowa z fuzji akcelerometru i żyroskopu – plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ruchy głowy liczone z obu czujników HALO (dokładny kąt przechyłu/pochylenia), a lewo/prawo działa przechyłem albo obrotem głowy.

**Architecture:** `HeadTilt` (tools/gestures/tilt.py) dostaje opcjonalny żyroskop: filtr komplementarny na kierunku pionu zastępuje wygładzanie akcelerometru, obrót = całka prędkości wokół pionu. Wykrywanie lewo/prawo bierze większą z dwóch składowych (przechył/próg, obrót/próg) w jednym stanie kierunku. Serwer (`backend/`) podaje żyroskop, ma ustawienia obrotu i dwa kroki kalibracji obrotu.

**Tech Stack:** Python 3.13, numpy, FastAPI, pytest/unittest; strona ustawień w czystym JS.

**Spec:** `docs/superpowers/specs/2026-11-15-glowa-fuzja-imu-design.md`

## Global Constraints

- Bazą jest stan na żywo z głównego checkoutu (`gesty-arcade`, niezacommitowany) przeniesiony do tego worktree (Task 0).
- Bez commitów, dopóki użytkownik nie poprosi. Bez restartu serwera na żywo, przebudowy aplikacji macOS i zmian w głównym checkoucie.
- Nie zapisywać `tools/models/gestures.joblib` (model jest kopiowany, nie linkowany).
- Python: `PY=/Users/stanislawsikora/Projects/NeuroHackathon/backend/.venv/bin/python`, komendy z katalogu worktree.
- Osie: x do przodu, y w górę, z w prawo; `dg/dt = −ω × g`; pochylenie w górę = +Gyro_z, przechył w lewo = −Gyro_x, obrót w lewo = +(ω·ĝ). Żyroskop w °/s.
- Wartości ze spec: próg przechyłu 15° (bez zmian), próg obrotu domyślnie 20°, obrót domyślnie włączony, τ fuzji ≈ 0,5 s, waga akcelerometru → 0 przy |a| różnym od typowego o > ~10%, dryf żyroskopu = mediana z ~4 s spoczynku, obrót wraca do 0 ze stałą ~20 s, kalibracja obrotu: 2 kroki po 3 s, próg = 0,45 × największy obrót, granice 12–40°, `EXIT_FRACTION` i `REPEAT_S` bez zmian.
- Bez żyroskopu (`gyro=None`) `HeadTilt` działa dokładnie jak dziś (istniejące testy `tools/tests/test_tilt.py` przechodzą bez zmian).
- Teksty dla użytkownika po polsku.

## Review Focus

1. Luka w danych w środku ruchu (telefon gubi 12–30% próbek) → żadnego gestu, dopóki głowa nie wróci do środka; pion odtworzony z akcelerometru (test w Task 1).
2. Szarpnięcie bez obrotu (liniowe przyspieszenie ±3 m/s² przez 0,2 s) → żadnego gestu (Task 1).
3. Stały dryf żyroskopu 1°/s przy nieruchomej głowie przez 120 s → żadnego obrotu jako gestu (Task 2).
4. Obrót i przechył naraz w tę samą stronę → jeden gest; obrót w lewo z lekkim przechyłem w prawo → tylko lewo (Task 2).
5. Powrót do środka po trzymanym 3 s obrocie (także z przelotem 8° za środek) → nie jest gestem (Task 2).

---

### Task 0: Stan na żywo w worktree

**Files:** cały diff `git diff HEAD` głównego checkoutu + nieśledzone pliki kodu; kopia modelu; link do sesji.

- [ ] **Step 1: Przenieś niezacommitowany stan** (drzewo bazowe `cccde39` = `e6c03d8`, więc diff wejdzie czysto)

```bash
M=/Users/stanislawsikora/Projects/NeuroHackathon
git -C $M diff HEAD --binary | git apply --index
for f in macos/Sources/BrainGestures/HeadCalibrationView.swift \
  mobile/controller/app/src/main/kotlin/pl/halorush/controller/{BackendHttp,HeadMapView,ModeIcon,ServerAddress}.kt \
  mobile/controller/app/src/test/kotlin/pl/halorush/controller/{BackendHttpTest,ScreensTest,ServerAddressTest}.kt; do
  mkdir -p "$(dirname $f)"; cp "$M/$f" "$f"; done
cp -R $M/mobile/controller/app/src/main/res/values-v27 mobile/controller/app/src/main/res/
mkdir -p tools/models tools/training && cp $M/tools/models/gestures.joblib tools/models/ && ln -s $M/tools/training/sessions tools/training/sessions
```

- [ ] **Step 2: Sprawdź zgodność:** `diff <(git -C $M diff HEAD --stat) <(git diff HEAD --stat)` – pusto.
- [ ] **Step 3: Testy bazowe:** `$PY -m pytest tools/tests -q` i `$PY -m pytest backend/tests -q`. Zapisz wynik (liczba passed/failed) – to punkt odniesienia; znana niestabilność: `test_e2e.py::test_eeg_phone_gestures_reach_arcade`.

---

### Task 1: Fuzja pionu w `HeadTilt`

**Files:**
- Modify: `tools/gestures/tilt.py` (`HeadTilt.__init__`, `reset`, `push`; nowe stałe)
- Test: `tools/tests/test_tilt.py` (nowy helper `Imu`, klasa `FusionTest`)

**Interfaces:**
- Produces: `HeadTilt.push(acc, gyro=None) -> list[dict]`; atrybuty `g` (pion, wektor jednostkowy), `fused: bool` (ostatni push z żyroskopem), `bias` (°/s, 3), `yaw` (°, + = w lewo; w tym tasku liczony, wykrywanie w Task 2). Stałe: `FUSION_TAU_S = 0.5`, `ACC_TRUST_BAND = 0.10`, `GYRO_BIAS_S = 4.0`, `STILL_DPS = 8.0`, `TURN_LEAK_S = 20.0`.

- [ ] **Step 1: Helper testowy `Imu`** w `test_tilt.py`: generuje spójne `acc` (3×n, m/s²) i `gyro` (3×n, °/s) przy FS=250. Stan: pion w układzie czujnika `gs` (start `NEUTRAL/|NEUTRAL|`). Metody: `hold(s)`, `move(kind, deg, s)` z `kind` ∈ `pitch` (oś z, + = w górę), `roll` (oś x, ujemna prędkość = w lewo), `yaw` (oś = `gs`, + = w lewo), profil prędkości półsinusowy; w każdej próbce `gs ← norm(gs − radians(ω)×gs·dt)`, `acc = 9.81·gs`. Opcje: `bias` (°/s dodawany do gyro), `jolt(s, vec)` (dodaje liniowe przyspieszenie do acc, gyro = 0), szum jak `Signal`.

- [ ] **Step 2: Testy (mają nie przejść)**

```python
class FusionTest(unittest.TestCase):
    def test_fused_angle_tracks_fast_tilt_without_lag(self):
        # przechył 25° w 0,15 s: kąt z fuzji ≥ 22° już na końcu ruchu (sam akcelerometr z LP: wyraźnie mniej)
    def test_jolt_without_rotation_is_not_a_gesture(self):
        # 2 s spokoju, jolt(0.2, [0, 0, 3.0]), 1 s spokoju -> run_imu(...) == [] ; ten sam sygnał bez gyro daje gest albo kąt > 10°
    def test_gyro_bias_estimated_when_still(self):
        # bias=[0.5, -0.8, 1.0], 6 s spokoju -> np.allclose(ht.bias, [0.5, -0.8, 1.0], atol=0.1)
    def test_gap_mid_move_no_gesture_until_center(self):
        # przechył w lewo do 10°, reset() (luka), dalej do 25° i trzymanie -> brak gestu; powrót do środka, potem przechył 25° -> ["head_left"]
    def test_without_gyro_unchanged(self):
        # ten sam Signal przez push(acc) i push(acc, None) daje identyczne zdarzenia i kąty
```

`run_imu(imu, chunk=5, **kw)` – jak `run`, ale `ht.push(acc[:, s:s+chunk], gyro[:, s:s+chunk])`.
Run: `$PY -m pytest tools/tests/test_tilt.py -q -k Fusion` → FAIL (push nie przyjmuje gyro).

- [ ] **Step 3: Implementacja w `HeadTilt.push`** – pętla po próbkach jak dziś; gdy `gyro` podany:

```text
a = acc_i; na = |a|; â = a/na
typowa |a| (g0): mediana |a| z pierwszej sekundy, potem z próbek spoczynku
ω = radians(gyro_i − bias)
ĝ ← norm(ĝ − (ω × ĝ)·dt)                                    # predykcja żyroskopem
w = clip(1 − |na/g0 − 1| / ACC_TRUST_BAND, 0, 1)
ĝ ← norm(ĝ + (dt/FUSION_TAU_S)·w·(â − ĝ))                   # korekta akcelerometrem
yaw ← yaw·exp(−dt/TURN_LEAK_S) + degrees(ω·ĝ)·dt
spoczynek: |gyro_i − bias| < STILL_DPS i |na/g0 − 1| < 0.05 → próbka do deque (GYRO_BIAS_S·fs); co 25 próbek bias = mediana
```

Pierwsza próbka i pierwsza po `reset()`: `ĝ = â`. Start: `bias` = mediana pierwszej sekundy. `reset()` dodatkowo: `g = None`, `yaw = 0` (dryf i g0 zostają). Reszta (`WARMUP_S`, środek, `_step`) bez zmian – czyta `self.g`.

- [ ] **Step 4:** `$PY -m pytest tools/tests/test_tilt.py -q` → wszystkie PASS (stare też).

---

### Task 2: Obrót głowy i lewo/prawo „albo”

**Files:**
- Modify: `tools/gestures/tilt.py` (`HeadTilt._step`, `apply_calibration`, `thr_turn`; `TiltCalibrator.add_turn`, `result`; `TiltScreen.push`)
- Modify: `tools/engine.py:548-549,585` (żyroskop do `TiltScreen`)
- Test: `tools/tests/test_tilt.py` (`TurnTest`, rozszerzenia `CalibrationTest`, `ScreenTest`)

**Interfaces:**
- Consumes: z Task 1 `HeadTilt.push(acc, gyro)`, `yaw`.
- Produces: `HeadTilt(fs, threshold_deg=DEFAULT_DEG, refractory_s=REPEAT_S, turn_deg=DEFAULT_TURN_DEG, turn=True)`; atrybuty `turn_threshold: float`, `turn_enabled: bool`, `cal_turn: dict[str, float]`; `thr_turn(d) -> float`; zdarzenie `{"t", "event", "kind": "tilt", "via": "tilt"|"turn", "angle", "confidence": 1.0}`. `TiltCalibrator.add_turn(direction: str, yaw_deg: float)`; `result()["turn"] = {"head_left": {"angle_deg", "threshold_deg"}, "head_right": {...}}`. `apply_calibration` czyta `cal["turn"]` (brak = progi domyślne). `TiltScreen.push(acc, gyro=None)`, stan zawiera `"turn_deg": float`. Stałe: `DEFAULT_TURN_DEG = 20.0`, `TURN_CAL_FRACTION = 0.45`, `TURN_CAL_LIMITS = (12.0, 40.0)`, `TURN_CAL_MIN_DEG = 10.0`.

- [ ] **Step 1: Testy (mają nie przejść)**

```python
class TurnTest(unittest.TestCase):
    def test_turn_left_and_right(self):          # obrót 45° w 0,4 s, trzymanie 1,5 s, powrót; w obie strony
        # labels == ["head_left", "head_right"] i via == "turn"
    def test_return_after_held_turn_not_gesture(self):   # obrót 50°, trzymanie 3 s, powrót z przelotem 8°
        # labels == ["head_left"]
    def test_turn_and_tilt_together_one_gesture(self):    # yaw +40° i roll w lewo 25° jednocześnie
        # labels == ["head_left"]
    def test_turn_left_with_slight_right_tilt(self):      # yaw +45°, roll w prawo 10°
        # labels == ["head_left"]
    def test_tilt_and_nod_do_not_trigger_turn(self):      # przechył 45° i skinienie 40° z obrotem 8° po drodze
        # wszystkie zdarzenia mają via == "tilt"
    def test_drift_1dps_still_120s_no_gesture(self):      # bias [0, 1.0, 0], 120 s spokoju
        # run_imu(...) == []
    def test_turn_disabled(self):                         # HeadTilt(FS, turn=False), obrót 45° -> []
    def test_turn_threshold_from_calibration(self):       # cal["turn"]["head_left"]["threshold_deg"] = 30: obrót 25° -> [], 35° -> ["head_left"]
class CalibrationTest(...):
    def test_turn_calibration(self):    # add_turn("head_left", y) dla y z ruchu do 50° -> threshold 22.5 (0,45·50); 6° -> None; 100° -> 40
class ScreenTest(...):
    def test_screen_uses_gyro(self):    # TiltScreen.push(acc, gyro) przy obrocie: state["turn_deg"] > 20
```

Run: `$PY -m pytest tools/tests/test_tilt.py -q -k "Turn or turn or gyro"` → FAIL.

- [ ] **Step 2: Implementacja `_step`**: składowe kierunku: `head_up/down` = kąt/`thr(d)`; `head_left` = max(kąt/`thr(d)`, `yaw`/`thr_turn(d)`), `head_right` = max(kąt/`thr(d)`, `−yaw`/`thr_turn(d)`) (obrót tylko gdy `turn_enabled` i `fused`). Gest dla największego wyniku ≥ 1; `via` = składowa, która go dała; koniec ruchu, gdy obie składowe aktywnego kierunku < `EXIT_FRACTION`; `armed` po luce wymaga, by wszystkie składowe były < `EXIT_FRACTION`. Środek obrotu = 0 (dryf usuwa przeciek `TURN_LEAK_S`).
- [ ] **Step 3: `TiltCalibrator.add_turn` / `result()["turn"]`**: największy obrót w stronę kierunku (+ dla lewo, − dla prawo); próg jak w Interfaces, `None` poniżej `TURN_CAL_MIN_DEG`. `TiltScreen.push` przekazuje gyro. `engine.py`: `ix_gyro` z `("Gyro_x","Gyro_y","Gyro_z")` (pusty, gdy brak) i `tilt.push(arr[ix_acc], arr[ix_gyro] if ix_gyro else None)`.
- [ ] **Step 4:** `$PY -m pytest tools/tests -q` → PASS.

---

### Task 3: Serwer: ustawienia, potok, kalibracja w grze, strona

**Files:**
- Modify: `backend/settings.py` (stałe, `default_settings`, `validate`, `FLAGS`)
- Modify: `backend/sessions.py` (`EegPipeline.__init__/set_turn/process`, `EegSession.__init__/apply_settings/_merge_tilt/head_thresholds/snapshot/_handle`)
- Modify: `backend/calibration.py` (`plan`, `_HEAD_TEXT`, `_collect`, opis modułu)
- Modify: `backend/static/index.html` (kontrolki obrotu przy `#tiltDeg`, tekst podpowiedzi)
- Modify: `backend/README.md` (sekcja ruchów głowy, kalibracja)
- Test: `backend/tests/test_settings.py`, `test_calibration.py`, `test_sessions.py`

**Interfaces:**
- Consumes: Task 2 `HeadTilt(..., turn_deg, turn)`, `push(acc, gyro)`, `yaw`, `turn_threshold`, `turn_enabled`, `thr_turn`, `TiltCalibrator.add_turn`, `result()["turn"]`.
- Produces: ustawienia `head_turn: bool = True`, `head_turn_deg: float = 20.0` (zakres `TURN_RANGE = (8.0, 60.0)`); `EegPipeline(..., head_turn=True, head_turn_deg=20.0)`, `EegPipeline.set_turn(enabled: bool, threshold_deg: float)`; `pipeline.motion["yaw"]`; snapshot gracza: `"turn_deg": {"head_left", "head_right"}`, `"turn_on": bool`; kroki kalibracji `turn_left`, `turn_right` (`kind="turn"`, `gesture` = `head_left`/`head_right`, 3 s) po `head_down`.

- [ ] **Step 1: Testy (mają nie przejść)**
  - `test_settings.py`: domyślne `head_turn is True`, `head_turn_deg == 20.0`; `head_turn_deg=5` → `ValueError`; `head_turn="tak"` → `ValueError`.
  - `test_calibration.py`: zaktualizuj `test_plan_matches_spec` – klucze `[..., "head_down", "turn_left", "turn_right", "double_blink_1", ...]`, sekundy `[8.0] + [3.0]*6 + [2.5]*9`, suma `48.5`; `test_steps_advance_by_samples` – 2425 kawałków po 5 próbek, `len(started) == 15`. Nowy `test_turn_steps_set_turn_threshold`: `motion={"g": ..., "yaw": y}` z obrotem do 50° w `turn_left` → `result["head"]["turn"]["head_left"]["threshold_deg"] == 22.5`. Nowy `test_turn_steps_are_not_face_background`.
  - `test_sessions.py`: `test_pipeline_feeds_gyro_to_head` (spójny obrót przez `_chunk`/nowy helper `turned(...)` → zdarzenie `head_left`, `via == "turn"`); `test_apply_settings_updates_turn` (`head_turn=False` → `pl.tilt.turn_enabled is False`); `test_calibration_done_applies_turn_threshold`; `hub.log[0]["via"] == "turn"` dla zdarzenia z obrotu.

  Run: `$PY -m pytest backend/tests/test_settings.py backend/tests/test_calibration.py backend/tests/test_sessions.py -q` → FAIL.

- [ ] **Step 2: Implementacja.** `process()` woła `self.tilt.push(chunk[self.ix_acc], chunk[self.ix_gyro])`, `motion` dostaje `"yaw": round(self.tilt.yaw, 1)`. `Calibration._collect`: krok `turn` → `self._tilt.add_turn(step.gesture, motion["yaw"])` i bez danych twarzy (jak `head`); `feed` przekazuje `motion` dalej. `_merge_tilt` przenosi `"turn"` z kalibracji w grze. `_handle`: `via=o.get("via") or o.get("kind", "model")`. Teksty kroków: tytuł „Obróć głowę w lewo”, polecenie „Obróć głowę w lewo.”, podpowiedź „Obróć głowę w lewo jak przy patrzeniu w bok, potem wróć na środek.” (prawo analogicznie). Strona: `<input type="checkbox" id="turnOn">`, suwak `#turnDeg` (8–60, krok 1) z `#turnOut`, zapis jak `#tiltDeg`; podpowiedź: głowa z akcelerometru i żyroskopu, lewo/prawo = przechył albo obrót.
- [ ] **Step 3: Stare testy z syntetycznym skokiem.** Testy podające skokową zmianę `g` przy zerowym żyroskopie (fizycznie niespójne) przepnij na helper `turned/tilted_move` ze spójnym żyroskopem albo wydłuż trzymanie do ≥ 1,5 s – nie zmieniaj oczekiwanego zachowania.
- [ ] **Step 4:** `$PY -m pytest backend/tests -q` → PASS (poza znaną niestabilnością e2e – powtórzyć 2×).

---

### Task 4: Ocena na nagraniach

**Files:**
- Create: `tools/evaluate_head.py`
- Modify: `backend/README.md` (tabela wyników), `docs/superpowers/specs/2026-11-15-glowa-fuzja-imu-design.md` (dobrane τ, jeśli inne niż 0,5)

**Interfaces:**
- Consumes: `HeadTilt`, `gestures.sessions.load_session(d)` (`x`, `channels`, `events`, `meta`).

- [ ] **Step 1: Skrypt** `$PY -I tools/evaluate_head.py [--sessions tools/training/sessions] [--recordings <dir>] [--tau 0.5]`. Warianty: `akcelerometr` (`push(acc)`, `turn=False`), `fuzja` (`push(acc, gyro)`, `turn=False`), `fuzja+obrót` (`turn=True`). Kawałki po 5 próbek; skok kolumny `Sample` → `reset()`.
  - Sesje `mode == "head"`: typ z instrukcji (`"przechyl"` → przechyły, inaczej obroty). Na polecenie (`cue` → najbliższy `return` + 0,5 s): trafienie = pierwsze zdarzenie ma etykietę polecenia; opóźnienie = t_zdarzenia − t_cue (mediana); zły kierunek; pominięte; zdarzenia poza oknami poleceń na minutę (w tym powroty).
  - Nagrania z gry (`--recordings`, domyślnie `/Users/stanislawsikora/Projects/NeuroHackathon/backend/recordings`): zdarzenia głowy na minutę, z podziałem `via`.
- [ ] **Step 2: Uruchom** dla τ ∈ {0,3; 0,5; 0,8}; wybierz τ z najlepszymi trafieniami przy nie gorszym opóźnieniu i liczbie zdarzeń poza poleceniami. Ustaw `FUSION_TAU_S` na wybraną wartość.
- [ ] **Step 3: Kryteria:** w sesjach przechyłów `fuzja` ≥ `akcelerometr` (trafienia) i mediana opóźnienia nie większa; w sesjach obrotów `fuzja+obrót` ≥ 90% trafień i powroty jako gest ≤ 5%; w nagraniach z gry `fuzja+obrót` ≤ 1,2 × zdarzeń `akcelerometr` – jeśli więcej, sprawdź (`via`) przed oddaniem. Wpisz tabelę do `backend/README.md`.

---

### Task 5: Pełna weryfikacja

- [ ] **Step 1:** `$PY -m pytest tools/tests -q` → PASS.
- [ ] **Step 2:** `$PY -m pytest backend/tests -q` (2×) → PASS poza znaną niestabilnością e2e.
- [ ] **Step 3:** `cd macos && swift build` nie jest potrzebne (Swift bez zmian); sprawdź tylko `$PY -I -c "import ast,sys; ast.parse(open('tools/engine.py').read())"`.
- [ ] **Step 4:** Raport dla użytkownika: wyniki oceny, co zmienione, co wymaga zgody (przeniesienie do głównego checkoutu, restart serwera, restart aplikacji macOS).
