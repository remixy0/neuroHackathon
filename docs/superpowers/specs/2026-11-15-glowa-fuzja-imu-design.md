# Głowa z akcelerometru i żyroskopu naraz (fuzja IMU)

Data: 2026-11-15. Stan wyjściowy: wersja na żywo z `gesty-arcade` (niezacommitowana), w której głowa idzie
tylko z akcelerometru (`tools/gestures/tilt.py`, `HeadTilt`).

## Po co

Użytkownik chce, żeby ruchy głowy były liczone z obu czujników HALO, a dane były jak najdokładniejsze.
Lewo/prawo ma działać **i przechyłem (ucho do ramienia), i obrotem głowy** – który pierwszy przekroczy próg.

Co pokazały nagrania (sesje treningowe 14–15.11 i nagrania z gry `backend/recordings/2026-11-15_04*`):

- Oba czujniki są w tym samym układzie osi i w °/s: całka żyroskopu = 0,96 zmiany kąta z akcelerometru
  (spoczynek → trzymany ruch, 25 prób). Osie zgodne z prawoskrętnym układem `dg/dt = −ω × g`:
  pochylenie w górę = +Gyro_z, przechył w lewo = −Gyro_x, obrót w lewo = +Gyro_y (≈ rzut na pion).
  Telefony (SDK Kotlin) dają te same osie co aplikacja macOS.
- Sam akcelerometr przekłamuje przy szybkim ruchu: w grze |a| = 8,1–12,4 m/s² (p1–p99), czyli błąd kąta
  do kilkunastu stopni przy progu 15°. Żyroskop tego nie ma, ale dryfuje – akcelerometr dryf koryguje.
- IMU odświeża się 50 Hz (SDK powtarza odczyt przy 5 próbkach EEG).
- Obrót wokół pionu rozdziela ruchy czysto: obroty 37–80° (p10 ≥ 28°) przy 8–14° przechyłu; przechyły
  i skinienia dają 2–11° obrotu przy 36–80° przechyłu/pochylenia.

## Cele

1. Kąt przechyłu i pochylenia z fuzji obu czujników: szybki (żyroskop) i bez dryfu (akcelerometr), odporny
   na szarpnięcia.
2. Obrót głowy w lewo/prawo jako drugi sposób na gest lewo/prawo (próg w stopniach od środka osoby).
3. Jeden ruch = jeden gest, także gdy osoba jednocześnie obraca i przechyla głowę. Powrót do środka nie jest gestem.
4. Pong analogowo dostaje dokładniejsze pochylenie bez zmian po stronie Arcade.
5. Pomiar na nagraniach: fuzja nie gorsza od obecnego akcelerometru (trafienia, opóźnienie, fałszywe gesty).

## Poza zakresem

- Model EEG i gesty twarzy/oczu (bez zmian).
- Interfejs aplikacji macOS (Swift): ekran „Kalibracja głowy” zostaje bez kroków obrotu.
- Restart serwera na żywo, przebudowa aplikacji, przeniesienie zmian do głównego checkoutu – dopiero za zgodą.
- Magnetometr (HALO go nie ma).

## Czego nie chcemy (porażka mimo działania)

- Więcej przypadkowych gestów głowy w grze niż teraz (rozglądanie się, rozmowa).
- Wolniejsza reakcja niż teraz.
- Zepsuty Pong analogowo albo kalibracja w grze.

## Podejścia

| | Na czym polega | Za | Przeciw |
|---|---|---|---|
| **A. Filtr komplementarny na grawitacji + obrót wokół pionu (wybrane)** | żyroskop obraca oszacowanie pionu w każdej próbce, akcelerometr powoli je koryguje (mniej, gdy \|a\| ≠ g); obrót = całka ω·ĝ | pasuje do obecnego `HeadTilt` (grawitacja, środek osoby, kalibracja), mało parametrów, łatwy do sprawdzenia | ruchy po skosie liczone przybliżenie (wystarcza przy ±80°) |
| B. Pełna orientacja (Madgwick/Mahony) | kwaternion i kąty względem neutralnej orientacji | dokładna przy złożonych ruchach | więcej kodu, kąty Eulera; obrót i tak dryfuje bez magnetometru |
| C. Filtr Kalmana z estymacją dryfu | stan: orientacja + dryf żyroskopu | teoretycznie najlepszy | strojenie szumów bez danych referencyjnych, trudny do sprawdzenia |

Odrzucone: dwa osobne detektory (przechył z akcelerometru „albo” prędkość z żyroskopu) – podwójne zgłoszenia
i powroty jako gesty, od których projekt już odszedł. Wybór A: decyzja Claude'a (użytkownik zostawił sposób).

## Projekt

### Fuzja (`tools/gestures/tilt.py`)

`HeadTilt.push(acc, gyro=None)`: z `gyro` (3×n, °/s) liczy fuzję; bez niego działa jak dziś (sam akcelerometr).

- Pion ĝ: w każdej próbce `ĝ ← norm(ĝ − (ω × ĝ)·dt)` (ω w rad/s po odjęciu dryfu), potem korekta
  `ĝ ← norm(ĝ + k·w·(â − ĝ))`, `k = dt/τ`, τ ≈ 0,5 s, `w` maleje do 0, gdy |a| odbiega od typowej długości
  (mediana |a| w spoczynku, więc jednostki akcelerometru są dowolne) o więcej niż ~10%.
- Dryf żyroskopu: mediana z ostatnich ~4 s próbek w spoczynku (mała prędkość, |a| ≈ g); start z pierwszej sekundy.
- Obrót: `yaw += (ω·ĝ)·dt` [°], + = w lewo; wraca do 0 ze stałą czasu ~20 s (jak dawny `HeadGyro`), więc
  dryf i trzymana postawa powoli stają się środkiem.
- Reszta `HeadTilt` bez zmian: środek osoby (mediana z 60 s), kierunki i progi z kalibracji, `angles` dla osi
  analogowej, `REPEAT_S`.

### Wykrywanie lewo/prawo „albo”

Dla lewo/prawo wynik kierunku = max(przechył/próg_przechyłu, obrót/próg_obrotu); góra/dół tylko pochylenie.
Gest, gdy wynik ≥ 1; ruch kończy się, gdy obie składowe spadną poniżej `EXIT_FRACTION` progu. Jeden stan na
kierunek, więc obrót z przechyłem daje jeden gest. Zdarzenie podaje, czym wyzwolono (`via`: przechył/obrót).

### Progi i ustawienia (`backend/settings.py`, strona ustawień)

- Przechył/pochylenie: jak dziś `head_tilt_deg` (15°) i kalibracja.
- Obrót: nowe `head_turn_deg` (domyślnie 20°: przechyły i skinienia dają do 11° obrotu, obroty od 28°)
  i przełącznik `head_turn` (domyślnie włączony). Na stronie: suwak i przełącznik obok progu głowy.

### Kalibracja w grze (`backend/calibration.py`)

Dwa nowe kroki po 3 s: „Obróć głowę w lewo”, „Obróć głowę w prawo” (+6 s). Próg obrotu osoby = 0,45 ×
największy obrót w tę stronę, w granicach 12–40°; za mały ruch → próg z ustawień. Kalibracja z aplikacji
macOS nie ma obrotu – wtedy próg z ustawień albo z kalibracji w grze.

### Serwer (`backend/sessions.py`) i aplikacja (`tools/engine.py`)

- `EegPipeline` podaje do `HeadTilt` akcelerometr i żyroskop.
- `TiltScreen` w aplikacji też dostaje żyroskop (podgląd i kalibracja liczone z fuzji).
- Luka w danych: pion od nowa z akcelerometru, obrót = 0, gest dopiero po powrocie do środka (jak dziś).
- Wyciszanie twarzy przy ruchu głowy bez zmian.

## Sprawdzenie

- Testy jednostkowe na syntetycznym sygnale: znany obrót daje właściwy kąt; skok liniowego przyspieszenia
  nie daje gestu; obrót z przechyłem = jeden gest; luka w danych; brak żyroskopu = zachowanie jak dziś.
- Skrypt oceny na nagraniach (porównanie: sam akcelerometr vs fuzja):
  - sesje przechyłów (15.11, Stas): trafienia na polecenie, opóźnienie od sygnału, zły kierunek, dodatkowe gesty;
  - sesje obrotów (14.11, 4 osoby): trafienia obrotem, powroty zgłoszone jako gest;
  - nagrania z gry: gesty głowy na minutę (bez etykiet – czy fuzja i obrót nie dodają przypadkowych).
- Wszystkie testy `backend/tests` i `tools/tests`.

## Gdzie powstaje

Stan na żywo (niezacommitowany diff z głównego checkoutu, drzewo bazowe identyczne) przenoszony do tego
worktree; tu zmiana i testy. Przeniesienie do głównego checkoutu i restart serwera – osobno, za zgodą.

## Zostawione budowniczemu

Dokładne τ i próg wagi |a| (dobrać na nagraniach w podanych granicach), nazwy pól zdarzenia, układ kontrolek
na stronie ustawień.
