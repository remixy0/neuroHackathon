# HALO → Arcade: sterowanie grami gestami z EEG

Serwer FastAPI przyjmuje dane z aplikacji telefonu HALO Controller (kontrakt `WEBSOCKET.md`, v1),
rozpoznaje gesty modelem `tools/models/gestures.joblib` i wysyła przyciski do Arcade (Tetris, Pong, Runner).
Co robi każdy gest w każdej grze, ustawiasz na stronie `http://localhost:8000/`.

```text
HALO ──BLE── telefon ──WebSocket /ws/controller── ten serwer + model ──WebSocket (pad)── Arcade :8787
                                                        │
                                       strona ustawień http://<Mac>:8000/
```

## Uruchomienie

Raz (Python 3.13):

```bash
./backend/run.sh --install
```

Potem w dwóch terminalach:

```bash
cd arcade && npm run dev
```

```bash
./backend/run.sh
```

Serwer wypisuje adres dla telefonu, np. `ws://192.168.1.20:8000/ws/controller`. Wpisz go w aplikacji
HALO Controller i wybierz gracza 1 albo 2. Telefon i Mac muszą być w tej samej sieci; gdy macOS zapyta
o połączenia przychodzące dla Pythona, zezwól.

Serwer sam łączy się z Arcade pod `ws://localhost:8787` (adres zmienisz na stronie). Arcade nie wymaga
żadnych zmiennych środowiskowych. **Okno gry Arcade musi być widoczne na ekranie**: gra puszcza krótkie
naciśnięcia w pętli animacji, którą przeglądarka wstrzymuje w ukrytej karcie, więc w tle kolejne gesty
tego samego kierunku mogą przepaść.

## Strona ustawień

- **Pasek Arcade**: czy serwer jest połączony z Arcade, jaka gra jest włączona i której kolumny ustawień używa.
- **Gracz 1 / Gracz 2**: opaska (urządzenie, bateria, kontakt elektrod O1/O2/Fp2/Fp1), bieżące rozpoznanie,
  prawdopodobieństwo każdego gestu z czerwoną kreską progu tej sesji. Pierwsze 3 s po połączeniu to rozgrzewka
  filtrów. Wiersz „głowa od” pokazuje progi czterech kierunków głowy i ich źródło (z kalibracji w grze, z aplikacji
  albo z ustawień), „głowa teraz” — bieżące wychylenie względem środka. W trakcie kalibracji ekran pokazuje
  bieżący krok i pasek postępu, a w belce jest przycisk „Pomiń kalibrację”; po niej wynik (progi kierunków głowy,
  progi albo wyłączenie gestów twarzy) i „Kalibruj ponownie”.
- **Odstęp**: „Ten sam gest ponownie najwcześniej po” (domyślnie 0,8 s; aplikacja macOS ma 1,5 s). Liczony od chwili,
  gdy pewność gestu spadnie poniżej progu. Na nagraniach 0,8 s nie dało żadnego podwójnego zgłoszenia jednego ruchu.
  Gesty różne od siebie nie mają odstępu.
- **Ruch głowy od przechyłu / pochylenia** (domyślnie 15°, suwak 5–40°): głowa idzie zawsze z **fuzji
  akcelerometru i żyroskopu** (`tools/gestures/tilt.py`, ten sam kod co w aplikacji macOS), nigdy z modelu.
  Żyroskop obraca kierunek pionu w każdej próbce (szybko, bez opóźnienia), akcelerometr powoli usuwa jego dryf
  (stała czasu 0,5 s) i jest pomijany, gdy długość wektora przyspieszenia odbiega od typowej o ponad 10% — przy
  szybkim ruchu opaska na czole mierzy też przyspieszenie styczne i dośrodkowe (w grze 8,1–12,4 m/s²), które
  samemu akcelerometrowi myliło kąt o kilkanaście stopni. Dryf żyroskopu = mediana z 4 s spoczynku.
  **Lewo / prawo = przechył w bok (ucho do ramienia) albo obrót głowy** (patrz niżej), góra / dół = pochylenie.
  Położenie głowy liczy się względem jej środka (mediana postawy z ostatniej minuty), więc powrót do środka
  nigdy nie jest gestem, a przechylona i trzymana głowa daje jeden gest. Kolejny gest w tę samą stronę dopiero po powrocie poniżej
  połowy progu. Na nagraniach skinienia mają 37–41°; przy 15° trafione góra 68 z 72, dół 70 z 71, powroty
  zgłoszone jako gest 2. Suwak działa dla kierunków bez kalibracji — kalibracja (w grze albo w aplikacji)
  ustawia każdy kierunek osobno. Progi pewności głowy w tabeli nie działają. Dawne pola `head_gyro`
  i `head_gyro_dps` w `settings.json` są pomijane.
- **Lewo/prawo także obrotem głowy** (domyślnie włączone, próg 20°, suwak 8–60°): obrót wokół pionu liczy
  żyroskop (rzut prędkości na kierunek pionu). Obrót nie ma bezwzględnego środka, a ludzie nie wracają dokładnie
  na środek, więc środek obrotu dociąga się do postawy w spoczynku (stała 2 s), a ruch kończy się także przy
  niepełnym powrocie (poniżej progu i 40% szczytu); dryf żyroskopu ograniczony do ±3°/s na oś. Lewo/prawo idzie
  z tego, co pierwsze przekroczy swój próg — przechyłu albo obrotu — w jednym stanie kierunku, więc obrót
  z przechyłem daje jeden gest. Na nagraniach obroty mają 37–80° (p10 ≥ 28°), a przechyły i skinienia dają
  po drodze 2–11° obrotu. Obrót przechodzi przez lukę w danych bez zmian (luki z telefonu są częste i krótkie),
  pion po luce liczy się od nowa z akcelerometru. W logu gestu `via` to `tilt` albo `turn`.
- **Wyciszanie twarzy przy ruchu głowy** (domyślnie 1,5 s po ruchu szybszym niż 30°/s; 0 s wyłącza): ruch głowy
  przesuwa elektrody i model widzi wtedy szczękę albo czoło, więc gest twarzy lub oczu z modelu jest w tym czasie
  pomijany. Na nagraniach: fałszywe gesty twarzy w sesjach głowy 5,6 → 2,2 na minutę, trafione gesty twarzy
  248 → 226 z 256. Prędkość głowy liczy żyroskop ze wszystkich trzech osi (także przechył na bok), po odjęciu
  tła czujnika, z dokładnością do jednego pakietu.
- **Kalibracja na starcie sesji / Polecenia głosem / Zapis sesji na dysk**: opis niżej.
- **Co robi gest**: kliknij pole, wybierz przycisk na małym padzie i czas naciśnięcia. Kolumny: Menu (menu główne
  i ustawienia gry), Tetris, Pong, Runner. Obramowana kolumna jest teraz używana. Suwak „Próg” ustawia minimalną
  pewność gestu (wspólną dla gier). Przyciski „Gracz 1 / Gracz 2” wysyłają gest bez opaski.
- **Ostatnie gesty**: każdy gest i przycisk, który poszedł do Arcade („Arcade offline”, gdy gra nie działa;
  gesty nie są wysyłane później).

Ustawienia zapisują się od razu do `backend/settings.json`.

Domyślnie:

| Gest | Menu | Tetris | Pong | Runner |
|---|---|---|---|---|
| przechył albo obrót w lewo / w prawo | ◀ / ▶ | ruch | – | zmiana pasa |
| głowa w górę | ▲ | obrót | paletka płynnie za głową (analogowo) | skok |
| głowa w dół | ▼ | szybsze opadanie (400 ms) | paletka płynnie za głową (analogowo) | ślizg |
| długie mrugnięcie (oczy zamknięte ~0,5 s) | A (zatwierdź) | A (upuść) | – | A |
| spojrzenie w lewo / w prawo | ◀ / ▶ | ruch | – | zmiana pasa |
| zaciśnięcie szczęki, zmarszczenie czoła | – | – | – | – |

### Głowa analogowo albo cyfrowo

Każda gra ma tryb głowy (`head_mode` w `settings.json`, na stronie „Głowa w Pongu”):

- **cyfrowo** (Menu, Tetris, Runner): jeden przechył albo pochylenie = jedno naciśnięcie. Kolejne w tę samą stronę
  dopiero po powrocie głowy do środka (poniżej połowy progu), z odstępem tylko 0,25 s (EEG ma osobny, 0,8 s) —
  w Runnerze dwie szybkie zmiany pasa w tę samą stronę przechodzą. Na nagraniu sesji głowy (26 skinień góra/dół,
  przez atrapę telefonu, serwer i serwer Arcade) Runner dostał 13/13 skoków i 13/13 ślizgów, bez podwójnych.
- **analogowo** (domyślnie Pong; Arcade ma oś analogową tylko w Pongu): pochylenie głowy jest wysyłane do Arcade
  jako pozycja paletki `{"player":1,"pos":0..1}` (0 = góra) po każdym pakiecie telefonu, najwyżej 50 razy na
  sekundę i tylko przy zmianie (co 0,5 s także bez zmiany). Głowa prosto = środek, pełne wychylenie paletki
  przy `analog_range_deg` (domyślnie 20°; kalibracja ustawia je na połowę największego ruchu osoby w górę i w dół),
  martwa strefa 1,5° wokół środka. Wygładzanie: filtr One Euro (`gestures/tilt.py` `AnalogAxis`) — drżenie
  0,47° → 0,21° na pakiet, opóźnienie +0,04 s. Gesty głowy w górę/w dół nie idą wtedy jako przyciski (Arcade
  kasuje pozycję paletki po naciśnięciu góra/dół). Pozycja z zaległej paczki (> 0,25 s) nie idzie. Na nagraniu:
  przy trzymanej głowie w górę paletka średnio 0,20, w dół 0,78, w spokoju 0,46 ± 0,02; przechył w bok jej nie rusza.

Lewo/prawo to **przechył** (ucho do ramienia) **albo obrót**. Starsze sesje treningowe głowy (do 14.11) prosiły
o obrót, nowsze (tryb „Głowa” w aplikacji) o przechył. Ocena na obu (`tools/evaluate_head.py`, 15.11.2026; dane
kawałkami po 5 próbek jak z telefonu, opóźnienie liczone od sygnału, więc z czasem reakcji osoby):

| | sam akcelerometr (dawniej) | fuzja + obrót (teraz) |
|---|---|---|
| sesje przechyłów (2, 31 poleceń) | 31/31, opóźnienie 0,49 s, poza poleceniami 0,29/min | 31/31, 0,44 s, 0,00/min |
| sesje obrotów (7, 4 osoby, 284 polecenia) | 144/284 (lewo/prawo 6/141, góra/dół 138/143), zły kierunek 27, 2,52/min poza poleceniami | 273/284 (lewo/prawo 138/141, góra/dół 135/143), zły kierunek 1, powroty jako gest 1%, 1,74/min |
| nagrania z gry (14, 31 min, bez etykiet) | 15,2 gestu głowy/min | 11,2/min (przechył 8,1, obrót 3,1) |

Sama fuzja (bez obrotu) daje w grze 10,4/min: mniej gestów niż sam akcelerometr, przy tych samych trafieniach na
poleceniach — różnica to głównie fałszywe gesty z szarpnięć. Stała τ 0,3 / 0,5 / 0,8 s zmienia wyniki o 1–2 próby.

To „schemat 2” (15.11.2026): głowa z akcelerometru, a z EEG tylko mrugnięcie (A) i spojrzenia — szczęka
i czoło są w grach wyłączone (można je przypisać ręcznie). `settings.json` sprzed schematu 2 (bez pola
`schema`) jest przestawiany raz przy wczytaniu: szczęka i czoło tracą przyciski, a długie mrugnięcie
i spojrzenia bez przycisku dostają domyślne; reszta ustawień zostaje.
**Długie mrugnięcie** (`long_blink`) zastąpiło podwójne (`double_blink`, wcześniej pojedyncze `blink`) 15.11.2026.
Stary `settings.json` z przyciskiem dla `double_blink` albo `blink` przenosi go na `long_blink` (próg nie
przechodzi); dawne pole `blink_source` jest pomijane. Plik zapisze się w nowej postaci przy następnej zmianie na stronie.
Spojrzenia model trafia u nowej osoby w 61–68% — gdy przeszkadzają, wyłącz je w tabeli.

### Długie mrugnięcie z sygnału czoła

Od 15.11.2026 gest A to **długie mrugnięcie**: oczy zamknięte ok. pół sekundy. Zwykłe mrugnięcie na polecenie wygląda
w sygnale tak samo jak mimowolne (581 na polecenie i 142 mimowolne: ta sama siła i długość), a w grze ludzie mrugają
mimowolnie ok. 7 razy na minutę; podwójne trafiało ok. 6 na 10. Wykrywa je reguła na Fp1/Fp2 (`blinks.py`,
`LongBlink`), nie model (model nie zna tego gestu; jego klasy `blink` i `double_blink` są pomijane).

- Sygnał: (Fp1 + Fp2) / 2. Kierunek (+/−) zależy od założenia opaski. Siła mrugnięcia osoby, szum i odrzucanie skoków
  elektrod (≥ 400 µV albo 6 × siła; 1 s przerwy) liczone na paśmie 0,5–10 Hz z typowych szczytów jak dotąd.
- Zamknięcie liczone na paśmie 0,05–10 Hz (przy 0,1 Hz plateau zamkniętych oczu opada o ok. 40% w 1 s) i **względem
  poziomu sprzed zbocza**: w nagraniach z gry poziom Fp pływa o tyle co mrugnięcie, więc próg liczony od zera nie
  działał (przy dawnych progach ok. 14% trafień zamknięć wstrzykniętych w nagrania z gry).
- Początek: wzrost o 0,7 × siła w ciągu 0,2 s (wolny dryf, np. spojrzenie w górę, tego nie spełnia) po 0,5 s spokoju
  (rozrzut < 0,8 × siła — nie seria mrugnięć ani szarpanie elektrod). Trwa, póki sygnał jest wyżej niż przed zboczem
  o 0,35 × siła i nie spadł poniżej połowy szczytu; dłużej niż 2 s to przesunięcie poziomu (elektroda), nie oczy.
- Gest w chwili, gdy zamknięcie trwa próg osoby: domyślnie 0,4 s (mierzone ponad progiem utrzymania, ok. 0,5 s
  zamkniętych oczu), z kalibracji 0,6 × mediana jej zamknięć w granicach 0,3–0,7 s. Jeden gest na zamknięcie,
  najwyżej jeden na 0,8 s, 5 s rozgrzewki. Wyciszanie przy ruchu głowy jak dla gestów twarzy.
- Karta gracza pokazuje wiersz „mrugnięcie” (kierunek, siła, szum, próg czasu).

Ocena (`tools/evaluate_long_blink.py`; długich mrugnięć nikt jeszcze nie nagrał, więc każde wykrycie jest fałszywe):
w 31 min nagrań z gry (`backend/recordings`, bez kroków kalibracji) **0,94 fałszywego na minutę** po wyciszeniu przy
ruchu głowy (bez wyciszenia 2,9); w sesjach treningowych: głowa 0,6, czoło 1,4, klawiatura 2,8, oczy 3,3,
mrugnięcia 3,3, szczęka 4,7 na minutę (sesje pełne celowych ruchów twarzy). Trafienia zamknięć 0,6 s wstrzykniętych
w prawdziwe tło: ok. 50–60% w sesjach mrugnięć, ok. 20% w nagraniach z gry (dużo skoków elektrod i pływania) — to
tylko przybliżenie; prawdziwe trafienia pokaże nagranie celowych długich mrugnięć (cel ≥ 85%).

## Kalibracja

Każda sesja EEG zaczyna się kalibracją (24,5 s). Polecenia mówi komputer z serwerem (`say`, głos Zosia; bez
tego głosu głos domyślny, bez `say` — np. na Windows — kroki widać tylko na stronie). Do końca kalibracji gesty
nie idą do gry.

1. **Spokój, 5 s** — środek głowy (kierunek grawitacji) i tło EEG osoby.
2. **Przechył w lewo, w prawo (ucho do ramienia), głowa w górę, w dół, po 2 s** — dla każdego kierunku osobno:
   największe wychylenie od środka, kierunek ruchu tej osoby i próg = 0,45 × to wychylenie w granicach 6–25°.
   Ruch mniejszy niż 8° albo dalej niż 60° od spodziewanego kierunku się nie liczy → ten kierunek zostaje
   na progu z ustawień (albo z kalibracji z aplikacji, patrz niżej).
   Potem **obrót w lewo, w prawo, po 2 s**: próg obrotu = 0,45 × największy obrót w tę stronę w granicach
   12–40°; obrót mniejszy niż 10° → próg z ustawień.
3. **„Zamknij oczy na pół sekundy”, 3 razy po 2,5 s** — detektor długiego mrugnięcia (`blinks.py`) bierze z tych
   kroków kierunek sygnału mrugnięcia osoby (≥ 2 zgodne głosy) i jej próg czasu: 0,6 × mediana długości jej zamknięć
   (≥ 0,25 s) w granicach 0,3–0,7 s, przy co najmniej 2 zamknięciach; inaczej domyślne. Wpis `long_blink` w wyniku:
   `source: fp`, kierunek, głosy, wykryte/próby, `min_s`. Nic nie jest wyłączane.

Szczęka i czoło nie mają kroków (od 15.11.2026; w grach nie mają przycisków) — zostają na progach z ustawień.
Mechanizm progów modelu dla gestów twarzy (`calibration.FACE`: tło = kwantyl 0,95 pewności w spokoju i w krokach
innych gestów, próg = tło + 0,4 × (szczyt − tło) w granicach 0,15–0,95, gest bez 2 trafień wyłączony do końca
sesji) zostaje w kodzie: wystarczy dopisać gest do `FACE`, żeby wrócił jego krok.

Wynik nadpisuje progi z ustawień tylko w tej sesji. Suwak przesunięty po kalibracji zmienia pozostałe gesty
i inne sesje, a skalibrowane gesty tej sesji zostają. „Pomiń kalibrację” wraca do progów z ustawień, „Kalibruj
ponownie” zaczyna od nowa. Gdy grają dwie osoby, kalibracje idą po kolei (jeden głos naraz); czekający gracz
też nie wysyła jeszcze gestów. Ta sama opaska tego samego gracza wracająca w ciągu 30 s (zerwane Wi-Fi)
zachowuje wynik kalibracji.

Spojrzenia w lewo i w prawo nie są kalibrowane — zostają na progach z ustawień.

### Kalibracja głowy z aplikacji macOS

Ekran „Kalibracja głowy” w aplikacji BrainGestures zapisuje kalibrację ruchów głowy dla opaski do
`tools/training/calibration/tilt_<opaska>.json` (np. `tilt_BA-HALO-216.json`; ten sam kod `gestures/tilt.py`).
Sesja z telefonu wczytuje ją na starcie, gdy nazwa opaski z `hello` się zgadza, i od razu używa jej kierunków
i progów (bez kalibracji w grze albo zanim ta się skończy). Kalibracja w grze ma pierwszeństwo; kierunki, których
w grze nie dało się zmierzyć, biorą wartości z aplikacji. „Pomiń kalibrację” i „Kalibruj ponownie” wracają do
kalibracji z aplikacji. Środek głowy z pliku nie jest używany (opaska mogła być założona inaczej) — liczy się
na bieżąco z pierwszej sekundy i z mediany postawy.

## Nagrania sesji

Przy włączonym „Zapis sesji na dysk” każda sesja EEG trafia do `backend/recordings/<data>_P<gracz>_<opaska>/`
(poza gitem; ok. 2 MB na minutę na gracza):

- `eeg.csv` — surowe próbki, kolumny jak w `tools/training/sessions/<id>/eeg.csv` (`Sample` = numer próbki
  w telefonie, przeskok = zgubione próbki), a na końcu diagnostyka sieci: `phone_time_s` (zegar telefonu przy
  odbiorze z opaski; `arrival_unix − phone_time_s` minus najmniejsza taka różnica = opóźnienie w sieci),
  `phone_discarded` (próbki odrzucone przez telefon jako starsze niż 0,5 s) i `ble_missed` (narastający licznik
  próbek zgubionych na Bluetoothie); puste, gdy telefon ich nie wysyła;
- `events.csv` — kroki i wynik kalibracji, każdy gest wysłany do gry (z przyciskiem), gesty twarzy wyciszone
  przy ruchu głowy; `sample` wskazuje wiersz `eeg.csv`;
- `session.json` — gracz, opaska, kanały, liczba próbek.

Nagrania pozwalają porównać sygnał z telefonu z treningiem i douczyć model na danych z gry.

Na karcie gracza wiersz **sieć** pokazuje to samo na żywo: opóźnienie teraz / p95 z ostatnich ~10 s / max,
brakujące próbki (luki w numeracji) i ich odsetek, ile z nich zgubił Bluetooth, ile odrzucił telefon i ile było
przerw w dostawie dłuższych niż 0,3 s. Czerwony = p95 > 0,3 s albo brakuje > 5% próbek. Jeśli brakuje dużo,
a „Bluetooth zgubił” jest blisko tej liczby, winna jest opaska ↔ telefon (np. Wi-Fi 2,4 GHz na tym samym radiu);
jeśli rośnie opóźnienie i przerwy, winna jest sieć telefon ↔ komputer.

## Telefon w trybie ręcznym

Aplikacja w trybie `manual` (pad bez opaski) wysyła przyciski, które serwer przekazuje do Arcade bez zmian.
Jeden gracz może grać opaską, drugi padem.

## Bez opaski i bez telefonu

Atrapa telefonu odtwarza nagranie z `tools/training/sessions/` dokładnie tak, jak wysyłałby je telefon:

```bash
backend/.venv/bin/python -m backend.sim_phone --player 1                    # najnowsza sesja ruchów głowy
```

```bash
backend/.venv/bin/python -m backend.sim_phone --player 2 --csv tools/training/sessions/<id>/eeg.csv --speed 2
```

```bash
backend/.venv/bin/python -m backend.sim_phone --manual --player 2           # pad: wpisuj left, a, start…
```

Uwaga: nagrania sesji były użyte do treningu, więc rozpoznanie na nich jest lepsze niż na nowej osobie.

## Opcje

| Zmienna | Znaczenie |
|---|---|
| `PORT` | port serwera (domyślnie 8000) |
| `HALO_TOKEN` | wymagany token `Authorization: Bearer …` od telefonu (domyślnie brak) |
| `HALO_SETTINGS` | inny plik ustawień |
| `HALO_RECORDINGS` | inny katalog na nagrania sesji (albo `--recordings`) |

## Jak to działa

- `protocol.py`: walidacja wiadomości z `WEBSOCKET.md` (hello, samples, manual, stop) i kody błędów.
- `sessions.py`: rezerwacja gracza (drugi telefon na tym samym graczu dostaje `player_busy`), osobny rozpoznawacz
  na sesję w wątku. ACK narastający: pierwszy pakiet od razu, potem najwyżej co 250 ms (`app.ACK_INTERVAL_S`;
  ostatnie pakiety przed przerwą potwierdza zadanie w tle). Luka w numeracji próbek, próbki `is_dummy` albo przeciążenie kolejki
  zaczynają rozpoznawanie od nowa (tło osoby zostaje). Gest z danych starszych niż 1 s jest pomijany — wiek to
  czas w kolejce serwera plus spóźnienie w sieci liczone z zegara telefonu (`host_time_ns`), więc gesty z paczki
  zaległych pakietów po zacięciu Wi-Fi nie idą do gry (`late_s`, `late_max_s` w stanie gracza).
  Sesja EEG bez próbek przez 6 s jest zamykana (telefon sam zrywa po 5 s bez ack; wcześniej 3 s i 2 s — na hotspocie
  z iPhone'a każda przerwa w sieci kończyła sesję). Sesja prowadzi też kalibrację, trzyma jej progi i kolejkę
  kalibracji graczy, wycisza gesty twarzy przy ruchu głowy.
- `tools/gestures/tilt.py` (wspólny z aplikacją): gesty głowy z fuzji akcelerometru i żyroskopu (`HeadTilt`:
  przechył, pochylenie, obrót), kalibracja kierunków i obrotu (`TiltCalibrator`), zapis i odczyt kalibracji
  z aplikacji. `tools/evaluate_head.py`: porównanie na nagraniach. `sessions.MotionMeter`: prędkość głowy z żyroskopu
  do wyciszania gestów twarzy.
- `calibration.py`: kroki kalibracji liczone w próbkach i wyliczenie progów osoby (bez zegara i bez I/O).
- `voice.py`: polecenia głosem (`say`). `recording.py`: zapis sesji na dysk.
- `arcade.py`: połączenie z Arcade jako pad, ponawiane co 1–10 s; stan gry wybiera kolumnę ustawień.
- `app.py`: FastAPI (`/ws/controller`, `/ws/ui`, `/api/settings`, `/api/test`, `/api/calibration`, `/api/info`,
  `/`). `POST /api/calibration {"player": 1, "action": "skip" | "restart"}` pomija albo powtarza kalibrację.

## Testy

```bash
backend/.venv/bin/python -m pytest backend/tests -q
```

Testy obejmują protokół, ustawienia, połączenie z Arcade, sesje (także rozpoznanie gestów na prawdziwym
nagraniu) oraz całą ścieżkę: atrapa telefonu → serwer → atrapa Arcade.

Nie sprawdzono jeszcze z prawdziwym telefonem i opaską: wartości EEG z SDK Kotlin (konfiguracja fabryczna)
mogą mieć inną skalę niż nagrania treningowe z aplikacji macOS (wzmocnienie X8). Jeśli rozpoznanie na żywo
będzie słabe, zacznij od porównania poziomów sygnału na stronie z nagraniami.
