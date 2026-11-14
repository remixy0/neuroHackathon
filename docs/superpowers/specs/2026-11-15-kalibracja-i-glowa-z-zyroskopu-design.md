# Kalibracja na starcie sesji i głowa tylko z żyroskopu — projekt

## Po co

Na żywo z telefonu (BA HALO 216) model był mało pewny (mrugnięcie 0,22–0,36), a ruchy głowy w grze wywoływały
fałszywe gesty twarzy (B co chwilę w Runnerze). Użytkownik chce: ruchy głowy wyłącznie z żyroskopu (nie z modelu
uczonego na treningu), kalibrację żyroskopu i EEG na starcie każdej sesji gry, poprawę mrugnięć i podobnych.

## Decyzje

- **Głowa tylko z żyroskopu**: zawsze `HeadGyro`; zdarzenia head_* z modelu zawsze odrzucane; bez przełącznika.
- **Wyciszanie twarzy przy ruchu głowy**: gest twarzy/oczu z modelu pomijany, gdy w ostatnich `motion_mute_s`
  (domyślnie 1,5 s) prędkość głowy przekroczyła `motion_mute_dps` (30°/s). Nagrania: fałszywe gesty twarzy
  w sesjach głowy 5,6 → 2,2/min, trafione gesty twarzy 248 → 226/256. Rozdzielczość: jeden pakiet telefonu.
- **Kalibracja** (wybór użytkownika: głos z Maca + strona), na starcie każdej sesji EEG, ok. 45 s, gesty nie idą
  do gry:
  1. spokój 8 s (tło żyroskopu i EEG osoby),
  2. głowa: lewo, prawo, góra, dół po 3 s → próg żyroskopu osoby = 0,4 × mediana szczytowych prędkości
     (25–120°/s; za mało ruchów → próg globalny),
  3. twarz: mrugnięcie, szczęka, czoło po 3 razy na przemian, po 2,5 s → dla gestu g: tło = kwantyl 0,95
     pewności g w spokoju i w krokach innych gestów twarzy, szczyt = mediana maksimów w krokach g;
     próg = tło + 0,4 × (szczyt − tło) w granicach 0,15–0,95; gest działa, gdy szczyt > tło + 0,08 i co najmniej
     2 z 3 prób przekraczają próg; niedziałający gest jest wyłączony dla tej sesji.
  - Polecenia mówi `say -v Zosia` (brak głosu → domyślny, brak `say` → tylko strona); strona pokazuje krok,
    postęp, „Pomiń” i „Kalibruj ponownie”. Kalibracje graczy idą po kolei (jeden głos naraz).
  - Wyniki kalibracji nadpisują progi globalne tylko dla tej sesji; zmiana suwaków na stronie dotyczy reszty.
- **Zapis sesji EEG** na dysk (`backend/recordings/`, poza gitem): surowe próbki + zdarzenia (kroki kalibracji,
  gesty). Pozwala porównać sygnał z telefonu z treningiem i douczyć model na danych z telefonu.
- Ustawienia: `calibration`, `voice`, `record` (wł.), `motion_mute_s`, `motion_mute_dps`, `head_gyro_dps`;
  `head_gyro` usunięte (stary plik ustawień działa — nieznane pola są pomijane).

## Poza zakresem

Douczanie modelu na danych z telefonu, kalibracja spojrzeń, ekran kalibracji w Arcade.
