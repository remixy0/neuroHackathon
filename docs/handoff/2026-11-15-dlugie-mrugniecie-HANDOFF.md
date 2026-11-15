# Handoff: długie mrugnięcie zamiast podwójnego + krótsza kalibracja (stan 2026-11-15 06:57)

Przeczytaj w całości przed jakąkolwiek zmianą. Nic nie jest zacommitowane; użytkownik nie prosił o commit.

## 1. O co chodzi (decyzje użytkownika)

Użytkownik (po polsku, krótko) poprosił: „zmień mruganie na pojedyncze, tak żeby dobrze łapało, oraz skróć kalibrację”.
Na pytanie, jakie pojedyncze, wybrał **„Dłuższe”: oczy zamknięte ok. pół sekundy** (zwykłe mrugnięcie wygląda w sygnale
jak mimowolne – patrz §6). Zatwierdził projekt i plan, wybrał wykonanie „sam, po kolei” (bez subagentów).

- Projekt (zatwierdzony): `docs/superpowers/specs/2026-11-15-dlugie-mrugniecie-i-krotsza-kalibracja-design.md`
- Plan (zatwierdzony, zadania 0–5): `docs/superpowers/plans/2026-11-15-dlugie-mrugniecie.md`
- Dziennik postępu i decyzji: `docs/handoff/2026-11-15-dlugie-mrugniecie-ledger.md` (kopia
  `.superpowers/sdd/2026-11-15-dlugie-mrugniecie/progress.md` – dopisuj tam, to oryginał)

Wszystkie te pliki są w **worktree**:
`/Users/stanislawsikora/Projects/NeuroHackathon/.claude/worktrees/control-flow-data-processing-24b7ab`
(gałąź `claude/control-flow-data-processing-24b7ab`). Pracuj w nim, nie w głównym katalogu.

## 2. Gdzie co jest (trzy miejsca)

| Miejsce | Stan |
|---|---|
| Główny katalog `/Users/stanislawsikora/Projects/NeuroHackathon`, gałąź `gesty-arcade` | **kod na żywo**, niezacommitowany: fuzja głowy (akcelerometr+żyroskop, lewo/prawo przechyłem albo obrotem), podwójne mrugnięcie z Fp (`backend/blinks.py` – `DoubleBlink`), kalibracja 48,5 s. Testy: 343 passed. Ma też niedokończony `git rebase` (`.git/rebase-merge`) – patrz `docs/handoff/HANDOFF-2026-11-15.md`; nie ruszać bez zgody. |
| Worktree (wyżej) | = stan głównego katalogu z 06:4x (zsynchronizowany, `git diff HEAD --stat` identyczny; zmiany głównego katalogu są w **indeksie** worktree) **+ praca w toku** nad długim mrugnięciem (w drzewie roboczym, poza indeksem). |
| Serwer na żywo | `python -m backend` z głównego katalogu, port 8000, PID 77192 od 06:21, `nohup`, log `~/Library/Logs/BrainGestures/backend.log`. Działa na kodzie z głównego katalogu (fuzja głowy + podwójne mrugnięcie). |

Praca w toku jako łatka względem głównego katalogu: `docs/handoff/2026-11-15-dlugie-mrugniecie-WIP.patch`
(w worktree: `git diff` pokazuje zmiany w plikach śledzonych; `backend/blinks.py` i `backend/tests/test_blinks.py`
są w worktree nieśledzone – porównuj je z głównym katalogiem przez `diff -u`).

## 3. Postęp według planu

- **Task 0 – zrobione.** Worktree zsynchronizowany z `gesty-arcade` (baza: 343 testy passed).
- **Task 1 – zrobione.** `backend/blinks.py`: klasa `LongBlink` zastąpiła `DoubleBlink` (14 testów w
  `backend/tests/test_blinks.py` przechodzi). Interfejs: `LongBlink(fs)`, `push(fp (2,n) [Fp1,Fp2] µV) -> list[float]`
  (czasy wykryć, zegar detektora), `reset()`, `calibrate(windows) -> {"source": "fp", "polarity", "votes", "hits",
  "trials", "closures", "min_s"}`, `snapshot()` (z `min_s`), atrybuty `n`, `polarity`, `fixed_polarity`, `min_s`,
  `detections`, `closures`. Stałe: `K_ON 0.5`, `K_LOW 0.2`, `RISE_S 0.2`, `K_HOLD 0.35`, `DEFAULT_MIN_S 0.40`,
  `CAL_FRACTION 0.6`, `MIN_LIMITS (0.3, 0.7)`, `SLOW_BAND (0.1, 10)`, `POLARITY_SWITCH 1.5`.
- **Task 2 – W TOKU (kod się teraz nie importuje: `backend/sessions.py` nadal ma `from .blinks import DoubleBlink`).**
  - Zrobione: `backend/settings.py` (gest `long_blink` zamiast `double_blink`, `LEGACY = {"blink": "long_blink",
    "double_blink": "long_blink"}`, `RULE_GESTURES = {"long_blink": "fp"}`, pole `blink_source` usunięte – stare pliki
    z nim się wczytują, bo nieznane pola są pomijane; `GESTURE_PL["long_blink"] = "Długie mrugnięcie (oczy zamknięte
    ~0,5 s)"`), `backend/app.py` (`/api/info`: `in_model` prawda dla gestów z reguły, nowe pole `rule`).
  - Dopisane testy (mają przejść po dokończeniu): `test_settings.py::test_long_blink_replaces_double_blink`,
    `::test_old_double_blink_mapping_moves_to_long_blink`, `test_sessions.py::test_pipeline_long_blink_from_fp`,
    `::test_model_blink_classes_never_dispatched`, `test_app.py::test_info_long_blink_is_rule_based`.
  - **Do zrobienia w `backend/sessions.py`:**
    - import `LongBlink`; `EegPipeline`: usuń parametr `blink_source`, `_pending_blink_source`, `set_blink_source`;
      `self.blinks = LongBlink(fs)`; w `process()` zawsze `self.blinks.push(chunk[self.ix_fp])` → zdarzenia
      `{"t", "event": "long_blink", "kind": "fp", "confidence": 1.0}`; zdarzenia modelu `double_blink` i `blink`
      zawsze zerowane (jak `head_*`); wyciszanie przy ruchu głowy działa też na `long_blink` (obecna pętla `moving`).
    - `EegSession`: bez `blink_source` w konstruktorze potoku i w `apply_settings`; `_note_blink_window` dla
      `step.gesture == "long_blink"`; `_calibrate_blinks` bez warunku na `blink_source`, wpis
      `cal.result["gestures"]["long_blink"] = {**fp, "works": None, "threshold": None, "background": None, "peak": None}`;
      `_restore_blink_polarity` czyta `long_blink` i przywraca także `min_s` (`det.min_s = entry["min_s"]`);
      `SPOKEN`: `"long_blink": "długie mrugnięcie"` zamiast `double_blink`; docstringi.
  - **Do zrobienia na stronie `backend/static/index.html`:** usuń przełącznik źródła mrugnięcia (`blinkSource`,
    `#blinkFp`, `#blinkModel`, `showBlink`), `double_blink` → `long_blink` w `CLASS_ORDER`/`FACE_SHORT`/warunkach
    `fpBlink` (teraz zawsze z Fp: `g.id === 'long_blink'`), `blinkRow` bez warunku na `blink_source`, z `min_s`;
    przy gestach z `rule` nie pokazywać suwaka progu modelu („z sygnału czoła”).
  - **Stare testy** odwołujące się do `double_blink` / `blink_source` (grep w `backend/tests/`) przepnij na
    `long_blink` bez zmiany oczekiwanego zachowania; testy `DoubleBlink`-specyficzne już zastąpione w `test_blinks.py`.
  - README (`backend/README.md`): sekcja mrugnięcia (podwójne → długie, dlaczego, liczby z §6).
- **Task 3 – nie zaczęte.** Krótsza kalibracja w `backend/calibration.py`: `REST_S = 5.0`, `HEAD_S = 2.0` (głowa i
  obrót), `FACE = ("long_blink",)`, `FACE_S = 2.5`, `FACE_REPEATS = 3`, tekst kroku `("Zamknij oczy na pół sekundy",
  "Zamknij oczy na pół sekundy.", "Zamknij oczy, policz w myślach do jednego i otwórz.")`; klucze kroków
  `["rest", "head_left", "head_right", "head_up", "head_down", "turn_left", "turn_right", "long_blink_1",
  "long_blink_2", "long_blink_3"]`, sekundy `[5.0] + [2.0]*6 + [2.5]*3`, suma 24,5 s. Szczęka i czoło bez kroków
  (zostają na progach z ustawień). Testy w `test_calibration.py` / `test_sessions.py` mają zakodowane 16 kroków,
  48,5 s, kolejność poleceń głosowych – zaktualizuj. Nowe testy z planu (Task 3).
- **Task 4 – nie zaczęte.** `tools/evaluate_long_blink.py`: `LongBlink` po 5 próbek (przeskok `Sample` → `reset()`)
  na nagraniach z gry `/Users/stanislawsikora/Projects/NeuroHackathon/backend/recordings/*/eeg.csv` i sesjach
  `tools/training/sessions/` (w worktree to dowiązanie do głównego katalogu). Kryterium: < 1 fałszywe / min w grze.
  Ryzyko znane z §6: w grze dużo wolnych przesunięć Fp – jeśli fałszywych za dużo, dobieraj `K_ON` (0,4–0,8),
  `RISE_S` (0,1–0,3); testy Task 1 muszą dalej przechodzić.
- **Task 5 – nie zaczęte.** Pełne testy 2×; testowy serwer + atrapa telefonu (kalibracja 24,5 s, strona bez błędów);
  raport dla użytkownika z prośbą o ~2 min nagrania długich mrugnięć (sprawdzenie trafień, cel ≥ 85%).

## 4. Decyzje podjęte po drodze (z dziennika)

1. Kierunek automatyczny z histerezą 1,5× – otwarcie oczu daje szczyt w przeciwną stronę prawie tak duży jak
   zamknięcie i odwracało kierunek po kilku zamknięciach (test `test_closures_do_not_flip_polarity`).
2. `DEFAULT_MIN_S = 0.40` zamiast 0,45 ze spec: długość jest mierzona powyżej `K_HOLD`, ~0,09 s krócej niż oczy są
   zamknięte; 0,40 ≈ 0,5 s zamkniętych oczu (intencja spec), zwykłe mrugnięcie mierzy ~0,2 s.
3. W teście po kalibracji zamknięcie 0,42 s (przechodzi z progiem osoby 0,3, nie z domyślnym 0,4).

## 5. Jak pracować i testować

```bash
cd /Users/stanislawsikora/Projects/NeuroHackathon/.claude/worktrees/control-flow-data-processing-24b7ab
PY=/Users/stanislawsikora/Projects/NeuroHackathon/backend/.venv/bin/python
$PY -m pytest backend/tests/test_blinks.py -q -p no:cacheprovider          # Task 1: 14 passed
$PY -m pytest backend/tests tools/tests -q -p no:cacheprovider              # całość (~75 s)
```

- Model `tools/models/gestures.joblib` jest w worktree **kopią** (nie linkiem) – nigdy nie zapisuj modelu w głównym
  katalogu bez sprawdzenia `~/Library/Logs/BrainGestures/engine.log` i zgody.
- Testowy serwer bez ruszania żywego: konfiguracja `halo-backend-worktree-test` w `.claude/launch.json` worktree
  (127.0.0.1, port 8100 → narzędzie może przydzielić 8101, ustawienia w scratchpadzie z `voice: false`,
  `arcade_url: ws://127.0.0.1:9`). Atrapa telefonu:
  `$PY -m backend.sim_phone --url ws://127.0.0.1:8101/ws/controller --player 1 --csv tools/training/sessions/<id>/eeg.csv --speed 2 --chunk 5 --seconds 70`.
  Kalibrację na testowym serwerze wyłączysz `PUT /api/settings` z `calibration: false`.
- Proces: TDD (test najpierw, zobacz, że pada), każda odchyłka od planu = wpis `Ruling:` w dzienniku, zakończenie
  zadania przez skrypt `task-done` (superpowers:executing-plans), na końcu przegląd całości.

## 6. Dane, na których oparto decyzje

- Zwykłe mrugnięcie na polecenie vs mimowolne (sesje `*_blink`, `*_keys`): 581 vs 142 – ta sama siła i długość;
  próg łapiący 90% zamierzonych przepuszcza ~90% mimowolnych.
- Mimowolne mrugnięcia w grze: ~7 / min (29 min nagrań `backend/recordings/2026-11-15_0*`).
- Długość szczytów Fp (≥ 50% wysokości): czyste sesje mediana 0,16 s; ale 13% (sesje) i 34% (gra) „szczytów”
  trwa > 0,5 s – to wolne przesunięcia (spojrzenie w górę/dół, ruch głowy, elektrody), stąd wymóg stromego zbocza.
- Brak nagrań celowych długich mrugnięć – trafienia sprawdzi dopiero nagranie użytkownika.

## 7. Przeniesienie do gry na żywo (po skończeniu, tylko za zgodą)

1. Sprawdź, czy główny katalog zmienił się od synchronizacji (06:4x): porównaj `git -C <główny> diff HEAD` z bazą
   (indeks worktree: `git show :<plik>`); inne sesje (np. „Przegląd pracy poprzednich agentów”) mogą tam pracować.
2. Kopia zapasowa plików głównego katalogu, scalenie trójstronne plik po pliku:
   `git merge-file -p <główny>/<plik> <(git show :<plik>) <worktree>/<plik>` – konflikty rozwiązuj ręcznie, przed
   zapisem sprawdź, że pliki w głównym katalogu nie zmieniły się od kopii. Nowe pliki kopiuj tylko, jeśli nie istnieją.
3. Testy w głównym katalogu (`backend/.venv/bin/python -m pytest backend/tests tools/tests -q`).
4. **Restart serwera tylko za zgodą użytkownika**: najpierw `/ws/ui` (czy gracze połączeni), potem `kill <PID>`,
   dopisek `=== restart <data> (powód) ===` do logu i
   `nohup backend/.venv/bin/python -m backend >> ~/Library/Logs/BrainGestures/backend.log 2>&1 < /dev/null &`
   z głównego katalogu; sprawdź `/api/settings`.
5. Po restarcie pierwsze połączenie telefonu zrobi nową kalibrację (24,5 s, „Zamknij oczy na pół sekundy” ×3).
   Stary `backend/settings.json` (z `double_blink` i `blink_source`) wczyta się z przyciskiem przeniesionym na
   `long_blink`; plik zapisze się w nowej postaci przy następnej zmianie na stronie.

## 8. Otwarte sprawy dla użytkownika

- Nagranie ~2 min długich mrugnięć (np. aplikacja macOS, tryb „Klawiatura”, klawisz przy każdym zamknięciu oczu) –
  do sprawdzenia trafień.
- W `backend/settings.json` na żywo w menu przechył w prawo wciska „lewo” (stara sprawa z poprzedniego handoffu).
- Commit całości (`gesty-arcade` i ten worktree) – czeka na zgodę.
