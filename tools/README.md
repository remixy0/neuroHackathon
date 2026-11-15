# Rozpoznawanie czynności z czepka BrainAccess HALO

Program uczy się na nagraniach ze znacznikami i rozpoznaje, co robi użytkownik
(oczy, szczęka, głowa, czoło, spoczynek), podając procent pewności.

## Stan od 14.11.2026: start od zera

Wszystkie wcześniejsze dane (`training/samples.jsonl` + `raw/`), oba modele (`models/`) i ręczne znaczniki
nagrań (`labels/`) są w `archive/2026-11-14_przed-startem-od-zera/`. Nowe dane zbiera się wyłącznie w aplikacji
macOS, w trybach treningu (oczy, mruganie, głowa, czoło, szczęka, klawiatura), i zapisują się jako ciągłe sesje:

    training/README.md               opis formatu (po angielsku, z przykładem wczytania)
    training/sessions/index.csv      jedna linia na sesję
    training/sessions/<id>/eeg.csv, events.csv, intervals.csv, stimulus.csv, session.json, README.md

Zapis robi `session_recorder.py` (wywoływany przez `engine.py`). Opis trybów: `../macos/README.md`.

Model gestów uczy się z tych sesji: `train_gestures.py` → `models/gestures.joblib`, pomiar `evaluate_gestures.py`
(sekcja „Model gestów z sesji” na końcu). Pozostałe skrypty (`train.py`, `evaluate.py`, `recognize.py`, `live.py`,
`record_cues.py`) pracują na starym formacie danych i bez przywrócenia archiwum nie mają na czym działać;
sekcje między tą a ostatnią opisują tamten stan.

## Uruchamianie

```bash
cd tools
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt   # raz
.venv/bin/python train.py        # trenuje na wszystkich plikach z labels/ -> models/model.joblib
.venv/bin/python evaluate.py     # uczciwy pomiar skuteczności per czynność
.venv/bin/python train.py --z-surowych      # j.w., ale cechy prób z aplikacji liczone od zera z training/raw/
.venv/bin/python evaluate.py --z-surowych   # pomiar na cechach przeliczonych z surowych plików
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
- **rodzina** — prawdopodobieństwo grupy: oczy / mięśnie twarzy / ruch głowy / spoczynek.
  Rodzina jest dużo pewniejsza niż konkretna czynność; gdy czynność ma < 25%, program podaje tylko rodzinę.

Odtwarzanie nagrania, na którym model był trenowany, daje zawyżone pewności.
Prawdziwą skuteczność pokazuje `evaluate.py`.

## Pozycja głowy i oczu (analogowo)

Oprócz gestów program podaje ciągłą pozycję (`neuro/position.py`): w `--json` jako pole `position`,
w aplikacji jako karta „Pozycja” (co 0,1 s), w `live.py` na końcu linii stanu.

| pole | znaczenie |
|---|---|
| `head_x`, `head_y` | obrót i pochylenie głowy w % (−100…100; + = w prawo / w górę; 100% = 60° obrotu, 50° pochylenia) |
| `head_yaw_deg`, `head_pitch_deg` | to samo w stopniach |
| `eyes_x` | spojrzenie w bok w % (+ = w prawo; 100% = typowe spojrzenie w bok tej osoby) |
| `eyes_calibrated` | skala i kierunek oczu wzięte z prób spojrzeń tej osoby (ekran Trening) |
| `eyes_ok` | `false` = elektrody dryfują za szybko, odczyt oczu niepewny |

Głowa jest dokładna (obrót z żyroskopu, pochylenie z akcelerometru; zgodność z ruchami w danych
co do kilku stopni). Obrót nie ma stałego punktu odniesienia, więc długo utrzymany powoli wraca do 0
(ok. 30 s); pochylenie liczone jest względem typowej postawy z ostatniej minuty.
Oczy są szacunkowe: Fp1/Fp2 nie trzymają stałego poziomu, więc liczone są tylko szybkie ruchy oka,
a utrzymane spojrzenie wraca do środka w ok. 3 s. Kierunek zgadza się w ok. 80% spojrzeń,
mrugnięcie potrafi pokazać ok. 40%.

## Jak to działa

1. `neuro/recording.py` — czyta `.db` (na kopii, z dołączeniem WAL).
2. `neuro/pipeline.py` — filtry przyczynowe i cechy z okna 1,5 s (ruchy) i 4 s (widmo), co 0,25 s:
   żyroskop, wolne wychylenia Fp1/Fp2 (oczy), moc 30–110 Hz (mięśnie), względna moc alfa/theta
   w O1/O2. Poziomy są normalizowane biegnącą medianą z 60 s (różnice między osobami).
3. `neuro/dataset.py` — dociąga ręczne znaczniki (dokładność ±1,5 s) do faktycznych zrywów sygnału.
4. `neuro/model.py` — ExtraTrees (300 drzew; trening ok. 0,2 s).
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

Przydatne opcje: `--only jaw,frown` (dogranie samych słabych klas),
`--rest 60`, `--no-voice`.

Uwagi:
- Program szuka strumienia EEG w sieci i mierzy różnicę zegarów, więc powinien działać także
  z innego komputera niż nagrywający. Ta ścieżka nie była testowana z czepkiem — przy pierwszej
  sesji sprawdź, czy `evaluate.py` nie zgłasza „żaden znacznik nie mieści się w nagraniu”.
- Głos (Zosia) działa tylko na macOS; na Windows są same sygnały i tekst na ekranie.
- Sygnał „wróć” jest zapisywany w polu `returns`, ale nie jest używany do treningu.

## Dodawanie nagrań ze znacznikami ręcznymi

Dodaj plik `labels/<osoba>.json` (wzór: `labels/maciek.json`): ścieżka do `.db`, `offset_s`
(różnica między zegarem notatek a nagraniem), `person` (imię tej osoby wpisywane w aplikacji — żeby
`evaluate.py` nie liczył jej dwa razy), `events` (`[sekunda, etykieta]`) i `intervals`
(`[od, do, etykieta]` dla spoczynku). Potem `train.py` i `evaluate.py`.

## Usunięte gesty

Zamknięcie/otwarcie oczu i spojrzenie w górę/w dół są usunięte z aplikacji, modelu i danych
(dawne próby i znaczniki: `training/usuniete_oczy/`, nieużywane). Góra/dół wróciło na próbę z kropką
14.11.2026, ale nie działało (0–29% na tej samej osobie) i psuło resztę, więc usunięte ponownie.
Usta w lewo/w prawo są tylko wyłączone z treningu (`EXCLUDED_LABELS` w `neuro/dataset.py`).

## Skąd próby wiedzą, kiedy był ruch

| źródło | chwila ruchu | pola w `samples.jsonl` |
|---|---|---|
| kliknięcie gestu | pierwszy zryw sygnału 0,3–4 s po kliknięciu | `click_s`, `event_s` |
| kropka (spojrzenia, tryb „Oczy — kropka”) | ruch oka 0,1–1 s po ruchu kropki (tło: 0,8 s patrzenia na środek), inaczej +0,3 s | `stim_s`, `target` (dokąd pojechała kropka), `big_look` (duże spojrzenie poza ekran), `weak_live` (oznaczenie z nagrania przed przeliczeniem) |
| kamera (tryb „Kamera”) | zryw w czepku −0,4…+0,8 s wokół chwili z kamery | `source: "camera"`, `cam_conf` |

Do modelu gestów trafiają tylko próby z kropką z „dużych spojrzeń” (`big_look`) z widocznym ruchem oka;
śledzenie kropki (małe ruchy) służy wyłącznie kalibracji odczytu oczu.

Próba z kamery trafia do treningu tylko, gdy czepek potwierdzi ruch: zryw w sygnale; dla ruchów głowy
żyroskop musi pokazać ≥ 8° we właściwą stronę, a gesty twarzy i oczu są odrzucane, gdy głowa się
w tym czasie ruszała. Kalibracja odczytu oczu (`neuro/position.py`) dopasowuje skok sygnału do
położenia kropki (`target`).

## Emocje (tryb „Emocje” w aplikacji)

Próby emocji są osobnym zbiorem i nie trafiają do modelu gestów. Każda próba to nagranie spokoju
(krzyżyk) i wywołania emocji z oceną osoby (przyjemność, pobudzenie, siła, co czuła):

- `training/emotions.jsonl` — jedna linia na próbę: `emotion` (cel), `ratings`, `phases`
  (`[faza, sekunda startu]`), `source` (wspomnienie / materiał), `windows` — cechy okien 2 s co 1 s
  (log moce pasm delta–gamma w O1/O2/Fp1/Fp2, asymetria alfa `faa`, miary zakłóceń, `clean`);
- `training/emotions_raw/<id>.csv` — surowy sygnał całej próby.

```bash
.venv/bin/python emotions.py            # co zebrano, zmiany względem spokoju, asymetria alfa a ocena,
                                        # i czy z sygnału da się odróżnić przyjemne od nieprzyjemnych
```

Uwaga: 4 elektrody (O1, O2, Fp1, Fp2) to mało do emocji; czołowa asymetria alfa (Fp2 vs Fp1) jest
najczęściej opisywanym wskaźnikiem walencji, ale efekt jest słaby i wymaga wielu prób na osobę.

## Trening od zera z surowych plików

Każda próba z aplikacji ma surowy wycinek sygnału (`training/raw/<id>.csv`, od 2,5 s przed ruchem),
a `samples.jsonl` — etykietę, osobę i chwilę ruchu. `train.py --z-surowych` przelicza z nich cechy
od nowa (ten sam kod co na żywo, `neuro/pipeline.py`), więc po zmianie sposobu liczenia cech model
powstaje na całej historii bez ponownego nagrywania. Na żywo cechy są normalizowane medianą z 60 s
pracy czepka, której wycinek nie zawiera — zamiast niej bierzemy medianę okien sprzed ruchu ze
wszystkich prób danej osoby (`raw_dataset` w `neuro/appdata.py`). Sprawdzone 14.11.2026: model z tak
przeliczonych cech rozpoznaje gesty liczone na żywo tak samo jak model z zapisanych cech
(75% na tej samej osobie, 72% na nowej). Słabiej odtwarzają się tylko alfa/theta (okno 4 s).

Uwaga: aplikacja po każdej nowej próbie doucza model z cech zapisanych, więc nadpisze model
z `--z-surowych`; do porównań używaj `--out inny_plik.joblib`.

## Dane z aplikacji (ekran Trening)

Próby zbierane w aplikacji macOS zapisują się w `training/`: `samples.jsonl` (etykieta, osoba, cechy,
wynik modelu) i `raw/<id>.csv` (surowy sygnał próby; nagłówek = nazwy kanałów). Format jest opisany
w `training/README.md`, który powstaje przy pierwszej próbie. `train.py` i `evaluate.py` dołączają
te próby automatycznie.

## Aplikacja macOS

Aplikacja okienkowa łącząca się z czepkiem bezpośrednio przez Bluetooth jest w `../macos/`
(patrz `macos/README.md`). Korzysta z `engine.py` z tego folderu.

## Model gestów z sesji (`gestures/`)

Model uczy się wyłącznie z sesji treningowych z aplikacji (`training/sessions/`). Aplikacja (`engine.py` →
`gestures/live.py`) wczytuje `models/gestures.joblib` przy każdym połączeniu czepka; bez pliku rozpoznawanie
jest wyłączone, a nagrywanie sesji działa dalej. Douczania w aplikacji nie ma — po nagraniu nowych sesji:

```bash
.venv/bin/python train_gestures.py         # wszystkie sesje -> models/gestures.joblib (ok. 30 s)
.venv/bin/python evaluate_gestures.py      # walidacja + symulacja na żywo (ok. 2 min) -> raport w konsoli
.venv/bin/python evaluate_gestures.py --bez-trybu keys   # to samo bez sesji trybu klawiatury (porównanie)
.venv/bin/python -m gestures.selftest      # cechy na żywo == cechy z treningu
.venv/bin/python -m unittest discover -s tests -t .   # testy na danych syntetycznych
```

Po zmianie `MODEL_VERSION` (gestures/model.py) albo kodu cech trzeba ponownie uruchomić aplikację —
działający silnik trzyma stary kod w pamięci.

**Jak działa**
1. `gestures/sessions.py` — wczytuje sesje (`eeg.csv`, `events.csv`, `intervals.csv`, `session.json`);
   pomija nagrania demo, niedokończone i z wadliwym EEG (brak kontaktu, martwy kanał).
2. `gestures/onsets.py` — po każdym sygnale GO szuka faktycznego początku ruchu w sygnale (żyroskop dla
   głowy, wychylenie Fp dla mrugnięć i oczu, moc 30–110 Hz dla czoła i szczęki); „weak” = ruchu nie widać.
3. `gestures/session_windows.py` — okna 1,5 s: wokół początku ruchu (4 przesunięcia), z trzymania
   (czoło, szczęka), tuż przed sygnałem i z 10 s spokoju na początku sesji (spoczynek). Powroty (głowa do
   środka, kropka do środka, rozluźnienie) i płynne wodzenie za kropką nie dają okien.
4. `gestures/features.py` — filtry przyczynowe (ten sam kod w treningu i na żywo), 131 cech: żyroskop,
   akcelerometr, wolne wychylenia Fp1/Fp2/O1/O2, moc i przebieg EMG.
5. `gestures/model.py` — cechy względem tła osoby (dolny kwantyl okien z ostatniej minuty — tak samo
   w treningu i na żywo), Random Forest 500 drzew, próg zgłoszenia osobno dla każdej klasy (kwantyl 0,99
   prawdopodobieństwa w oknach spoczynku, liczony na osobach spoza treningu).
6. `gestures/recognizer.py` — strumień: okno co 0,1 s, wygładzanie, próg klasy, bez powtórzeń; ruch
   powrotny głowy rozpoznawany po kącie głowy. `gestures/validation.py` — podziały i symulacja na żywo.

**Sesje trybu klawiatury** (`keys`: osoba sama mruga / patrzy w bok i oznacza gest klawiszem W/S, A, D):
- początek ruchu szukany jest po obu stronach klawisza (0,8 s przed … 0,5 s po, najdalej do połowy drogi do
  sąsiedniego klawisza) po prędkości zmiany sygnału Fp; z kilku ruchów wygrywa ten najbliżej klawisza
  (`onsets.detect_key_onset`). `train_gestures.py` wypisuje dla każdej takiej sesji, przy ilu klawiszach ruch
  widać i jak daleko od klawisza się zaczyna;
- okna gestu jak w innych trybach, ale kończą się najpóźniej na początku następnego oznaczonego ruchu;
- czas między klawiszami to spoczynek o niskiej wadze (`model.GAP_WEIGHT`, rodzaj okna „gap”) — osoba mogła
  mrugnąć bez klawisza; okna, w których widać mrugnięcie, skok wzroku albo ruch głowy, są pomijane. Okna „gap”
  nie wchodzą ani do progów zgłoszeń, ani do oceny;
- `evaluate_gestures.py` liczy mrugnięcia i spojrzenia osobno w sesjach z poleceniami i w sesjach klawiatury,
  a `--bez-trybu keys` daje wynik bez nagrań z klawiatury — porównanie pokazuje, co te nagrania dały.

**Skuteczność (14.11.2026, 39 sesji, 4 osoby: Maciej, Oliwier, Staś, Urbanek; 10 klas)** — pełny raport:
`models/gestures_report.json`. Próba = jeden sygnał GO.

| gest | nowa osoba | nowa sesja znanej osoby | nowe próby tej samej sesji | na żywo, nowa osoba |
|---|---|---|---|---|
| wszystkie (próby) | 80% | 87% | 93% | 69% |
| głowa lewo / prawo / góra / dół | 100 / 100 / 94 / 99% | 100 / 100 / 96 / 99% | 100% | 99 / 100 / 93 / 99% |
| zmarszczenie czoła | 85% | 81% | 100% | 88% |
| spojrzenie w lewo / w prawo | 84 / 83% | 84 / 82% | 84 / 86% | 61 / 68% |
| szczęka | 81% | 84% | 87% | 78% |
| mrugnięcie | 66% | 84% | 97% | 50% |

Przy 25 sesjach (pierwsza godzina nagrań) było: nowa osoba 77%, nowa sesja 79%, na żywo 62% — dokładanie
sesji wyraźnie pomaga.
Na żywo poza próbami (przerwy, w których osoba też mruga i się poprawia): 6 fałszywych zgłoszeń na minutę.
Wnioski:
- **Głowa i czoło działają u każdego.** Głowa w górę myli się czasem ze szczęką (przy otwieraniu ust głowa
  lekko odchyla się do tyłu).
- **Mrugnięcie zależy od osoby**: u Maćka i Oliwiera model widzi je dobrze, u Urbanka wygląda jak
  zmarszczenie czoła (mocne zaciśnięcie powiek), u Stasia w późniejszych sesjach jest ledwo widoczne.
  Dla znanej osoby (jej sesje w treningu) trafność rośnie do 80–98% — model dla tej czwórki jest uczony
  na wszystkich ich sesjach.
- **Spojrzenia**: 2/3 skoków kropki daje ruch oka zbyt mały, by go wykryć w sygnale (kropka nie wychodzi
  poza ekran); te próby mają w treningu mniejszą wagę.
- Reguła „wycisz klasę, której u nowych osób model nie trafia” jest wyłączona (`UNRELIABLE_RECALL = 0`):
  wyciszała mruganie wszystkim, choć u połowy osób działało (na żywo 54% → 62% trafionych gestów).
- Dane do zebrania w pierwszej kolejności: kolejne osoby (dziś 4), więcej mrugania i czoła (czoło: 4 sesje).
