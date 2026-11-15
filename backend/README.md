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
  filtrów. W trakcie kalibracji ekran pokazuje bieżący krok i pasek postępu, a w belce jest przycisk
  „Pomiń kalibrację”; po niej wynik (próg głowy, progi albo wyłączenie gestów twarzy) i „Kalibruj ponownie”.
- **Odstęp**: „Ten sam gest ponownie najwcześniej po” (domyślnie 0,8 s; aplikacja macOS ma 1,5 s). Liczony od chwili,
  gdy pewność gestu spadnie poniżej progu. Na nagraniach 0,8 s nie dało żadnego podwójnego zgłoszenia jednego ruchu.
  Gesty różne od siebie nie mają odstępu.
- **Ruchy głowy z żyroskopu** (próg domyślnie 60°/s): głowa idzie zawsze z żyroskopu, nigdy z modelu. Gest
  głowy idzie, gdy prędkość obrotu albo pochylenia przekroczy próg we właściwą stronę. Powrót do środka (także
  z przelotem za środek do 20°) nie jest gestem. Na 10 nagraniach (42 min, 178 ruchów głowy):

  | | opóźnienie od początku ruchu | pominięte | powroty zgłoszone jako gest | przypadkowe ruchy głowy |
  |---|---|---|---|---|
  | model | 0,28 s | 0 | 44 | 3,8 / min |
  | żyroskop 60°/s | 0,02 s | 3 | 5 | 0,3 / min |

  Progi pewności głowy w tabeli nie działają. Dawne pole `head_gyro` w `settings.json` jest pomijane.
- **Wyciszanie twarzy przy ruchu głowy** (domyślnie 1,5 s po ruchu szybszym niż 30°/s; 0 s wyłącza): ruch głowy
  przesuwa elektrody i model widzi wtedy szczękę albo czoło, więc gest twarzy lub oczu z modelu jest w tym czasie
  pomijany. Na nagraniach: fałszywe gesty twarzy w sesjach głowy 5,6 → 2,2 na minutę, trafione gesty twarzy
  248 → 226 z 256. Prędkość głowy to obrót i pochylenie (bez przechyłu na bok), z dokładnością do jednego pakietu.
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
| głowa w lewo / w prawo | ◀ / ▶ | ruch | – | zmiana pasa |
| głowa w górę | ▲ | obrót | paletka w górę (300 ms) | skok |
| głowa w dół | ▼ | szybsze opadanie (400 ms) | paletka w dół (300 ms) | ślizg |
| zaciśnięcie szczęki | A (zatwierdź) | A (upuść) | – | A (skok) |
| zmarszczenie czoła | B (wstecz) | B (obrót w lewo) | – | B (ślizg) |
| mrugnięcie, spojrzenia | – | – | – | – |

Mrugnięcie i spojrzenia są wyłączone, bo u nowej osoby model trafia je w 50–68% (ruchy głowy ~98%).

## Kalibracja

Każda sesja EEG zaczyna się kalibracją (ok. 45 s). Polecenia mówi komputer z serwerem (`say`, głos Zosia; bez
tego głosu głos domyślny, bez `say` — np. na Windows — kroki widać tylko na stronie). Do końca kalibracji gesty
nie idą do gry.

1. **Spokój, 8 s** — tło żyroskopu i EEG osoby.
2. **Głowa w lewo, w prawo, w górę, w dół, po 3 s** — próg żyroskopu osoby = 0,4 × mediana szczytowych prędkości,
   w granicach 25–120°/s. Liczy się tylko ruch we właściwą stronę; mniej niż 3 wyraźne ruchy → próg z ustawień.
3. **Mrugnięcie, otwarcie ust, zmarszczenie czoła, po 3 razy na przemian, po 2,5 s** — dla każdego gestu: tło =
   kwantyl 0,95 jego pewności w spokoju i w krokach pozostałych gestów twarzy, szczyt = mediana maksimów w jego
   krokach, próg = tło + 0,4 × (szczyt − tło) w granicach 0,15–0,95. Gest działa, gdy szczyt > tło + 0,08
   i co najmniej 2 próby przekraczają próg; gest, który nie działa, jest wyłączony do końca sesji. Okna bez
   kontaktu elektrod się nie liczą; przy mniej niż 2 próbach z danymi gest zostaje na progu z ustawień.

Wynik nadpisuje progi z ustawień tylko w tej sesji. Suwak przesunięty po kalibracji zmienia pozostałe gesty
i inne sesje, a skalibrowane gesty tej sesji zostają. „Pomiń kalibrację” wraca do progów z ustawień, „Kalibruj
ponownie” zaczyna od nowa. Gdy grają dwie osoby, kalibracje idą po kolei (jeden głos naraz); czekający gracz
też nie wysyła jeszcze gestów. Ta sama opaska tego samego gracza wracająca w ciągu 30 s (zerwane Wi-Fi)
zachowuje wynik kalibracji.

Spojrzenia w lewo i w prawo nie są kalibrowane — zostają na progach z ustawień.

## Nagrania sesji

Przy włączonym „Zapis sesji na dysk” każda sesja EEG trafia do `backend/recordings/<data>_P<gracz>_<opaska>/`
(poza gitem; ok. 2 MB na minutę na gracza):

- `eeg.csv` — surowe próbki, kolumny jak w `tools/training/sessions/<id>/eeg.csv` (`Sample` = numer próbki
  w telefonie, przeskok = zgubione próbki);
- `events.csv` — kroki i wynik kalibracji, każdy gest wysłany do gry (z przyciskiem), gesty twarzy wyciszone
  przy ruchu głowy; `sample` wskazuje wiersz `eeg.csv`;
- `session.json` — gracz, opaska, kanały, liczba próbek.

Nagrania pozwalają porównać sygnał z telefonu z treningiem i douczyć model na danych z gry.

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
  na sesję w wątku, ACK każdego pakietu. Luka w numeracji próbek, próbki `is_dummy` albo przeciążenie kolejki
  zaczynają rozpoznawanie od nowa (tło osoby zostaje). Gest z danych starszych niż 1 s jest pomijany.
  Sesja EEG bez próbek przez 3 s jest zamykana. Sesja prowadzi też kalibrację, trzyma jej progi i kolejkę
  kalibracji graczy, wycisza gesty twarzy przy ruchu głowy.
- `headgyro.py`: gesty głowy z żyroskopu (próg prędkości, blokada powrotów, odstęp między gestami).
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
