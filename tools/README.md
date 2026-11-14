# Rozpoznawanie czynności z czepka BrainAccess HALO

Program uczy się na nagraniach ze znacznikami i rozpoznaje, co robi użytkownik
(oczy, usta, szczęka, głowa, czoło, stroboskop), podając procent pewności.

## Uruchamianie

```bash
cd tools
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt   # raz
.venv/bin/python train.py        # trenuje na wszystkich plikach z labels/ -> models/model.joblib
.venv/bin/python evaluate.py     # uczciwy pomiar skuteczności per czynność
.venv/bin/python recognize.py "../resources/maciek-1_ses-S001_task-_run-001_20261114_121223_eeg.db"
```

Nagranie Urbanka ma resztę danych w osobnym pliku WAL o innej nazwie:

```bash
.venv/bin/python recognize.py "../resources/urbanek-1_ses-S001_task-_run-001_20261114_120516_eeg.db" --wal "../resources/urbanek zlapany.db-wal"
```

Opcje `recognize.py`: `--realtime` (tempo rzeczywiste), `--json` (jedna linia JSON co 0,25 s
z pełnym rozkładem pewności — do podpięcia pod frontend), `--all` (pokazuj też spoczynek).

## Rozpoznawanie na żywo (LSL)

Włącz nadawanie LSL w BrainAccess Board i uruchom:

```bash
.venv/bin/python live.py
```

Program znajduje strumień typu EEG, pokazuje bieżące rozpoznanie w jednej odświeżanej linii
i dopisuje zakończone czynności jako kolejne wiersze. Opcje: `--name BA_HALO` (gdy strumieni jest
kilka), `--json` (linia JSON co 0,25 s), `--all` (pokazuj też spoczynek).

Pierwsze 10–20 s po starcie program poznaje poziomy sygnału danej osoby, więc początkowe
rozpoznania są mniej pewne — niech osoba chwilę posiedzi spokojnie.

Test bez czepka — w jednym terminalu nadaj nagranie jako strumień, w drugim uruchom `live.py`:

```bash
.venv/bin/python replay_lsl.py ../resources/maciek-1_ses-S001_task-_run-001_20261114_121223_eeg.db
```

```bash
.venv/bin/python live.py --name REPLAY_HALO
```

## Jak czytać pewność

- **pewność** — prawdopodobieństwo konkretnej czynności (np. „spojrzenie w lewo”).
- **rodzina** — prawdopodobieństwo grupy: oczy / mięśnie twarzy / ruch głowy / stroboskop / spoczynek.
  Rodzina jest dużo pewniejsza niż konkretna czynność; gdy czynność ma < 25%, program podaje tylko rodzinę.

Odtwarzanie nagrania, na którym model był trenowany, daje zawyżone pewności.
Prawdziwą skuteczność pokazuje `evaluate.py`.

## Jak to działa

1. `neuro/recording.py` — czyta `.db` (na kopii, z dołączeniem WAL).
2. `neuro/pipeline.py` — filtry przyczynowe i cechy z okna 1,5 s (ruchy) i 4 s (widmo), co 0,25 s:
   żyroskop, wolne wychylenia Fp1/Fp2 (oczy), moc 30–110 Hz (mięśnie), alfa i odpowiedź na
   stroboskop w O1/O2. Poziomy są normalizowane biegnącą medianą z 60 s (różnice między osobami).
3. `neuro/dataset.py` — dociąga ręczne znaczniki (dokładność ±1,5 s) do faktycznych zrywów sygnału.
4. `neuro/model.py` — las losowy (400 drzew).
5. `neuro/recognizer.py` — klasa `Recognizer`: `push(kawałek_próbek)` zwraca rozpoznania.
   Ten sam kod obsłuży strumień na żywo (LSL) — wystarczy podawać kawałki `(n_kanałów, n_próbek)`.

## Dogrywanie danych z automatycznymi znacznikami

`record_cues.py` prowadzi osobę przez sesję (polecenie głosem i na ekranie, sygnał „teraz”,
sygnał „wróć”) i zapisuje chwilę każdego sygnału w zegarze LSL, czyli tym samym, w którym
nagranie zapisuje próbki. Kolejność czynności jest losowa w każdej rundzie.

1. Włącz nagrywanie w BrainAccess Board.
2. Uruchom na komputerze, który nagrywa:

```bash
.venv/bin/python record_cues.py --person ania --reps 5
```

3. Po sesji zatrzymaj nagrywanie i przeciągnij plik `.db` do terminala, gdy program o to poprosi
   (albo wpisz ścieżkę później w pole `recording` pliku `labels/ania-<data>.json`).
4. `train.py`, potem `evaluate.py`.

Przydatne opcje: `--only mouth_left,mouth_right,jaw` (dogranie samych słabych klas),
`--strobe 7,9,11,13` (inne częstotliwości; muszą być na liście `STROBE_FREQS` w `neuro/pipeline.py`),
`--strobe ""` (bez stroboskopu), `--rest 60`, `--no-voice`.

Uwagi:
- Program szuka strumienia EEG w sieci i mierzy różnicę zegarów, więc powinien działać także
  z innego komputera niż nagrywający. Ta ścieżka nie była testowana z czepkiem — przy pierwszej
  sesji sprawdź, czy `evaluate.py` nie zgłasza „żaden znacznik nie mieści się w nagraniu”.
- Głos (Zosia) działa tylko na macOS; na Windows są same sygnały i tekst na ekranie.
- Sygnał „wróć” jest zapisywany w polu `returns`, ale nie jest używany do treningu.

## Dodawanie nagrań ze znacznikami ręcznymi

Dodaj plik `labels/<osoba>.json` (wzór: `labels/maciek.json`): ścieżka do `.db`, `offset_s`
(różnica między zegarem notatek a nagraniem), `events` (`[sekunda, etykieta]`) i `intervals`
(`[od, do, etykieta]` dla spoczynku i stroboskopu). Potem `train.py` i `evaluate.py`.
