# BrainGestures — aplikacja macOS

Natywna aplikacja (SwiftUI), która łączy się z czepkiem BrainAccess HALO bezpośrednio przez
Bluetooth (bez BrainAccess Board) i pokazuje na żywo rozpoznawane gesty z procentem pewności.

## Budowanie i uruchamianie

Wymaga Xcode (Swift) oraz gotowego środowiska w `../tools/.venv` (patrz `tools/README.md`).

```bash
./build.sh
```

```bash
open build/BrainGestures.app
```

Przy pierwszym skanowaniu macOS zapyta o zgodę na Bluetooth dla BrainGestures.

## Obsługa

1. Włącz czepek. Zamknij BrainAccess Board — czepek połączony gdzie indziej nie pojawi się na liście.
2. „Szukaj czepków” (ok. 5 s), potem „Połącz”.
3. Przez pierwsze 10–20 s niech osoba siedzi spokojnie (program poznaje poziomy sygnału).

Bez czepka: sekcja „Demo bez czepka” odtwarza nagrania z `resources/`.

Ekran „Rozpoznawanie”: sygnał z 4 elektrod i żyroskopu, pozycja głowy, bateria i kontakt elektrod;
bieżący gest, pewności i historia gestów pojawią się, gdy będzie nowy model.

## Dwa czepki naraz

„Dodaj drugi czepek” w panelu po lewej otwiera drugie gniazdo. Każde gniazdo ma własne imię
osoby, własne połączenie i własne rozpoznawanie (w zakładce „Rozpoznawanie” widać obie osoby obok
siebie). Każdy czepek ma osobny proces silnika (`tools/engine.py`), więc problem z jednym nie
zatrzymuje drugiego.

Trening z dwoma czepkami: sesja nagrywa obie osoby jednocześnie (te same polecenia i bodźce,
ten sam czas zegara), a każda osoba dostaje własny folder sesji. Oba czepki muszą mieć różne imiona.

Czepek 1 łącz pierwszy: czepek już połączony przestaje się ogłaszać, więc w drugim gnieździe
„Szukaj czepków” pokaże tylko ten drugi.

## Trening: osobna sesja dla każdej kategorii ruchu

Zakładka „Trening” ma osobny tryb dla każdej kategorii. Wybierasz tryb, czas (1–10 min) i klikasz
Start; resztę prowadzi aplikacja głosem i dźwiękami na czarnej planszy na całe okno. Esc albo
„Zakończ” przerywa sesję — dane do tej chwili zostają zapisane.

| Tryb | Co robi osoba | Etykiety w danych |
|---|---|---|
| **Oczy** | śledzi wzrokiem żółtą kropkę, która porusza się tylko w poziomie: skacze w bok (różna odległość) i wraca na środek, a co jakiś czas płynnie przejeżdża od krawędzi do krawędzi | `look_left`, `look_right`, `center`, `pursuit` |
| **Mruganie** | patrzy na krzyżyk i mruga raz po każdym piknięciu (co 2,5–4,5 s, losowo) | `blink` |
| **Głowa** | widzi i słyszy kierunek, na piknięcie obraca/pochyla głowę i trzyma 1,5 s, na drugi dźwięk wraca; lewo/prawo/góra/dół po równo w losowej kolejności | `head_left`, `head_right`, `head_up`, `head_down` |
| **Czoło** | na piknięcie marszczy czoło i trzyma 2 s, na drugi dźwięk rozluźnia | `frown` |
| **Szczęka** | na piknięcie otwiera szeroko usta i trzyma 1,5 s, na drugi dźwięk zamyka | `jaw` |
| **Klawiatura** | bez poleceń: sama mruga i patrzy w boki we własnym rytmie, a każdy gest od razu oznacza klawiszem — W lub S = mrugnięcie, A = spojrzenie w lewo, D = spojrzenie w prawo | `blink`, `look_left`, `look_right` |

Każda sesja zaczyna się od instrukcji czytanej na głos i 10 s spokoju (tło). Tryb „Emocje” jest
osobną zakładką i zapisuje dane po swojemu (opis w `tools/README.md`).

**Tryb klawiatury** nagrywa jedną osobę — tę, która siedzi przy klawiaturze (przy dwóch czepkach
wybierasz ją obok czasu). Po 10 s spokoju słychać piknięcie i klawisze zaczynają działać; klawisz
naciska się razem z gestem (tuż przed albo tuż po), gesty co 2–3 s, każdego mniej więcej tyle samo.
Plansza pokazuje krzyżyk, ostatni zapisany gest i liczniki. Klawisze są fizyczne (jak WASD w grach,
niezależnie od układu klawiatury), przytrzymanie klawisza liczy się raz. Esc albo „Zakończ” kończy
sesję normalnie (status `complete`); ustawiony czas to tylko górna granica. W danych każdy klawisz
to zdarzenie `key` z chwilą wciśnięcia wg systemu oraz odcinek `key_press` (0,8 s przed do 0,5 s po
klawiszu) w `intervals.csv`.

### Co się zapisuje

Każda sesja to osobny folder `tools/training/sessions/<data>_<osoba>_<tryb>/`:

- `eeg.csv` — ciągły surowy sygnał wszystkich kanałów czepka (250 Hz), z numerem próbki, czasem
  od początku i czasem zegara komputera;
- `events.csv` — każdy bodziec i polecenie (piknięcie, zapowiedź, ruch kropki, klawisz, początek/koniec
  tła) z numerem próbki, sekundą i czasem unix;
- `intervals.csv` — to samo jako gotowe odcinki z etykietą (tło, trzymanie ruchu, pozycja kropki,
  okolica klawisza);
- `stimulus.csv` — tylko w trybie oczu: pozycja kropki dla każdej próbki sygnału;
- `session.json` — osoba, czepek, opis każdego kanału z jednostką, dokładne parametry protokołu,
  model zegara i jego niepewność, jakość sygnału, liczniki;
- `README.md` — opis tej sesji słowami.

Obok jest `tools/training/README.md` (opis całego formatu po angielsku, z przykładem wczytania)
i `tools/training/sessions/index.csv` (jedna linia na sesję). Cały folder `tools/training/` można
wrzucić do zewnętrznego AI — opisy są pisane tak, żeby dane dało się zrozumieć bez tego kodu.

Na dole zakładki widać, ile danych (próby, minuty, sesje) ma już każda osoba w każdym trybie.

### Start od zera

14.11.2026 wszystkie wcześniejsze dane (pojedyncze próby z `samples.jsonl`), oba modele i ręczne
znaczniki nagrań trafiły do `tools/archive/2026-11-14_przed-startem-od-zera/`. Aplikacja nie ma
teraz żadnego modelu: zakładka „Rozpoznawanie” pokazuje sygnał i pozycję głowy, ale gestów nie
rozpoznaje, dopóki z nowych sesji nie powstanie nowy model. Tryb z kamerą, trening przez klikanie
kafelków i tryb automatyczny zostały usunięte.

## Jak to jest zbudowane

- `Sources/BrainGestures/` — interfejs. Uruchamia silnik `tools/engine.py` jako proces potomny
  i czyta jego linie JSON.
- `tools/engine.py` — łączy się z czepkiem przez oficjalne SDK `brainaccess`, zapisuje sesje
  treningowe (`tools/session_recorder.py`) i rozpoznaje gesty, gdy istnieje model
  `tools/models/gestures.joblib` (teraz go nie ma — patrz „Start od zera”).
- Aplikacja nie jest samodzielna: `build.sh` wpisuje do niej ścieżkę do `tools/`, więc po
  przeniesieniu repozytorium trzeba ją zbudować ponownie.

## Założenia do sprawdzenia

- Kolejność elektrod czepka przyjęta jako O1, O2, Fp2, Fp1 (tak jak w nagraniach z Board).
  Inną kolejność ustawia zmienna `BA_ELECTRODES` w `tools/engine.py`.
- Wzmocnienie ×8, 250 Hz.

## Diagnostyka

Silnik zapisuje polecenia i zmiany stanu do `~/Library/Logs/BrainGestures/engine.log`
(obok jest `bacore.log` z SDK BrainAccess).
