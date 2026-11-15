# Handoff: podwójne mrugnięcie z sygnału Fp (stan na 2026-11-15 ok. 05:10)

## Zadanie (zatwierdzone przez użytkownika: „Tak, zrób”)

W serwerze gry (`backend/`) wykrywać **podwójne mrugnięcie** (`double_blink`, w grach = przycisk A) regułą
na sygnale Fp1/Fp2 (dwa szczyty mrugnięcia w krótkim odstępie), zamiast klasy `double_blink` z modelu.
Powód: walidacja krzyżowa modelu (`tools/models/gestures_report.json`) – `double_blink` trafia 90% w tej samej
sesji, ale **0% w nowej sesji tej samej osoby** (mylone ze zwykłym mrugnięciem). Model nie może policzyć dwóch
mrugnięć w odstępie 0,3–0,5 s (okno 1,5 s + odstęp 0,8 s między powtórzeniami tej samej etykiety).

## Co już zrobione w tej rozmowie (przed handoffem)

- **Model przeszkolony** (`tools/train_gestures.py`) na 48 sesjach (4 osoby, w tym nowe sesje Stasia z
  04:34 head i 04:44 keys z 101× double_blink). Wdrożony jako `tools/models/gestures.joblib` (04:50).
  Kopie: `tools/models/gestures_2026-11-15_0200.joblib` (poprzedni), `gestures_report_2026-11-14_2343.json`.
  Nowy raport: `tools/models/gestures_report.json` (evaluate_gestures.py, 7 min).
- **Serwer gry zrestartowany** za zgodą użytkownika o 04:59: `nohup backend/.venv/bin/python -m backend`
  (log `~/Library/Logs/BrainGestures/backend.log`), PID był 52869. Wcześniejszy serwer (PID 41501) uruchomiła
  inna sesja Claude – zatrzymany. Przed kolejnym restartem: sprawdź `/ws/ui` (gracze) i zapytaj użytkownika
  (pamięć projektu `halo-backend-live`).
- Odpowiedź dla użytkownika: nie nagrywać więcej double_blink; nagrywać pojedyncze mrugnięcia (W) i
  spojrzenia (A/D) w trybie klawiatury, więcej osób i osobne założenia czepka.

## Pomiar sygnału (docs/handoff/blinks_explore.py)

Filtr 0,5–10 Hz na (Fp1+Fp2)/2. Wnioski:
- **Polaryzacja mrugnięcia zależy od sesji** (+ w większości, − u Maciej 212053 i Stas 044449) → kierunek
  trzeba ustalać na bieżąco (lub z kalibracji).
- **Amplituda 24–900 µV** zależnie od osoby/sesji → próg względny (np. 0,45 × kwantyl 0,995 z ostatniej minuty,
  z dolnym ograniczeniem 5×MAD i 15 µV).
- Mrugnięcia na polecenie (tryb blink, Oliwier/Urbanek): czyste pojedyncze szczyty (48/49).
- Sesje klawiatury są gęste (klawisz co ~1 s), więc okno wokół klawisza łapie sąsiednie mrugnięcia – liczenie
  szczytów w nich jest zaszumione. Odstęp dwóch szczytów w double_blink: mediana 0,33–0,64 s.

## Roboczy detektor + pomiar (docs/handoff/dbl_eval.py) – W TOKU

`DoubleBlink` (streaming, próbka po próbce): filtr ze stanem, co 1 s statystyki z 60 s (polaryzacja = znak
większego kwantyla 0,995/0,005, próg = max(k×amplituda, 5×MAD, 15 µV)), szczyt = przekroczenie progu do
spadku poniżej połowy progu, podwójne = dwa szczyty w odstępie 0,15–0,7 s, odstęp 0,8 s między podwójnymi,
rozgrzewka 8 s. Skrypt porównuje warianty (k 0,35/0,45/0,55, max_gap 0,55/0,7/0,9) i liczy:
trafione double_blink w sesjach klawiatury (2026-11-15_044449, 015550), pojedyncze mrugnięcia uznane za
podwójne (wszystkie sesje `*_blink`), podwójne na minutę w sesjach head/jaw/frown/eyes.
Uruchomienie (z katalogu repo): `backend/.venv/bin/python -I docs/handoff/dbl_eval.py` (kilka minut).
**Wyników jeszcze nie ma** – przerwane przez handoff.

## Następne kroki

1. Uruchom `dbl_eval.py`, dobierz parametry (cel: dużo trafień, mało pojedynczych → podwójnych, < ~0,3/min
   w innych sesjach). Porównaj z modelem (CV: 0% w nowej sesji).
2. TDD: `backend/blinks.py` (klasa jak `DoubleBlink`) + `backend/tests/test_blinks.py` na syntetycznym sygnale
   (dwa szczyty 0,4 s → jedno zdarzenie; jeden szczyt → nic; szczyty 1,2 s → nic; odwrócona polaryzacja →
   działa; szum → nic; rozgrzewka).
3. Podłączenie w `backend/sessions.py` → `EegPipeline.process`: zdarzenia `blink`/`double_blink` z modelu
   odrzucać (jak head_*), dokładać zdarzenia z `DoubleBlink.push(chunk[ix Fp1, Fp2])` jako
   `{"t", "event": "double_blink", "kind": "eog", "confidence": 1.0}`; wyciszanie przy ruchu głowy stosować
   też do nich; reset przy luce (`reset()`).
4. Kalibracja (`backend/calibration.py`, FACE zawiera double_blink, krok „Mrugnij dwa razy” ×3): może ustawić
   polaryzację i amplitudę detektora z tych kroków zamiast progu modelu.
5. Pełne testy: `backend/.venv/bin/python -m pytest backend/tests -q` (+ `tools/tests`), README backendu,
   restart serwera tylko za zgodą użytkownika, commit na gałęzi `gesty-arcade` gdy użytkownik poprosi.

## Uwaga o stanie repo

Na gałęzi `gesty-arcade` jest dużo niezacommitowanych zmian innych sesji (backend: kalibracja, tilt z
akcelerometru, analogowy Pong; mobile/; macos/). Nie cofać ich. Dane i `*.joblib` są w `.gitignore`.


## Wynik (2026-11-15 ok. 06:10, kolejna sesja) — ZROBIONE w kodzie, serwer na żywo jeszcze bez tego

Pomiar `dbl_eval.py` (prototyp powyżej): 35/152 trafione — próg z kwantyla 0,995 łapał skoki elektrod (1000-4000 µV,
mrugnięcia 15-250 µV), a „4×MAD” w gęstych sesjach leżał ponad mrugnięciami. Ustalenia z nagrań:
- odstęp szczytów w podwójnym: 0,20-0,30 s (mediana 0,25); szybkie pojedyncze mruganie: 0,40-0,67 s → okno 0,12-0,40 s,
- drugie mrugnięcie bywa 15-50% pierwszego (siedzi na przerzucie filtra) → drugi próg niższy (0,25 vs 0,4 amplitudy),
- kierunek (+/-) z przewagi szczytów jest trafny tylko w ~66% (przerzut filtra 0,5 Hz po mrugnięciu bywa równie
  duży); niższy filtr górnoprzepustowy był gorszy (dryf). Wariant „odbicie od doliny” łapał więcej, ale 2-5 fałszywych/min.
- sesja 044449 po ~105 s jest nasycona (kontakt elektrody) — liczone osobno jako „czyste”.

Wdrożone (`backend/blinks.py`, testy `backend/tests/test_blinks.py`, ocena `docs/handoff/dbl_eval_fp.py`):
58% czystych trafionych (63% gdy kierunek znany), 8,8% serii szybkich pojedynczych → podwójne, 1,0/min w innych
sesjach. Model: 0% w nowej sesji; w nagraniach z telefonu (backend/recordings) nie wysłał ani jednego double_blink.
Podłączenie: `EegPipeline` (blink_source "fp" domyślnie, "model" na stronie), kalibracja ustala kierunek
z kroków „Mrugnij dwa razy” (≥2 zgodne głosy, krok z artefaktem nie głosuje), wyciszanie przy ruchu głowy,
wiersz „mrugnięcie” na karcie gracza. W nagraniach z telefonu kroki kalibracji mają często ogromne artefakty
po ruchu głowy z poprzedniego kroku i mało widocznych mrugnięć — kierunek zwykle zostaje automatyczny.

Do zrobienia: nagrać kilka sesji gry z podwójnym mrugnięciem na żywo i sprawdzić fałszywe A; ewentualnie dłuższa
przerwa między krokiem głowy a „Mrugnij dwa razy” w kalibracji.
