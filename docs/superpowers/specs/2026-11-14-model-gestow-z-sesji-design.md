# Model gestów z sesji treningowych — projekt (zatwierdzony 14.11.2026)

## Po co
Po „starcie od zera" aplikacja BrainGestures nie ma modelu. Z nagrań w `tools/training/sessions/`
(25 sesji, 4 osoby, 2 czepki BrainAccess HALO) ma powstać nowy model rozpoznający gesty, razem z
uczciwym pomiarem dokładności, przygotowany na dokładanie kolejnych nagrań.

## Cele
- Model 10 klas: `rest`, `blink`, `look_left`, `look_right`, `frown`, `jaw`, `head_left/right/up/down`.
- Dokładność mierzona osobno dla nowej osoby (bez niej w treningu) i dla nowej sesji znanej osoby:
  trafność każdego gestu, macierz pomyłek, fałszywe zgłoszenia na minutę.
- Każde rozpoznanie na żywo ma pewność; gest zgłaszany dopiero powyżej progu swojej klasy.
- Dołożenie danych = nagranie sesji + `train_gestures.py`. Raport trzyma historię kolejnych treningów.

## Poza zakresem
- Zmiany w aplikacji macOS i w `engine.py`. Model ma pasować do obecnego interfejsu
  (`models/gestures.joblib`, `gestures.model.MODEL_VERSION`, `GestureRecognizer`).
- Sieć neuronowa na surowym sygnale.

## Czego unikamy
- Wyniku zawyżonego przez przeciek (okna jednej próby/sesji w treningu i teście naraz).
- Podmiany `models/gestures.joblib` bez pytania — czyta go działająca aplikacja.
- Udawania, że gesty niewidoczne w sygnale działają.

## Ustalenia z danych
- Głowa (żyroskop) i zmarszczenie czoła (EMG 6–15×): bardzo wyraźne u wszystkich.
- Mrugnięcie: wyraźne, amplituda 35–300 µV zależnie od osoby i sesji.
- Szczęka: słaba, u Macieja praktycznie niewidoczna.
- Spojrzenie lewo/prawo (kropka w oknie): u 3 z 4 osób 0–7 µV w Fp1−Fp2, tylko Stas ok. 30 µV.
- Stas nie ma sesji głowy.

## Podejścia
1. **Cechy + klasyfikator klasyczny, wybierany walidacją (wybrane).** Przyczynowe cechy okna 1,5 s
   (żyroskop, EOG, EMG), normalizacja do tła osoby, klasyfikator wybrany w walidacji „nowa osoba".
   Działa przy małej liczbie osób, te same cechy w treningu i na żywo.
2. Sieć na surowym sygnale — odrzucone: 4 osoby i ~30 prób na gest, przeuczy się.
3. Reguły progowe bez uczenia — odrzucone jako całość: dobre dla głowy, nie rozróżnią czoła/szczęki/mrugnięcia
   między osobami; nie poprawiają się z danymi.

## Jak
- `gestures/sessions.py`: loader formatu `braingestures-session/1`; każdy folder sesji brany automatycznie
  (pomija `demo`, niekompletne i z wadliwym sygnałem — z podaniem powodu).
- Początek ruchu wykrywany w sygnale po każdym `cue` (żyroskop dla głowy, Fp dla mrugnięć/oczu, EMG dla
  czoła/szczęki); brak wyraźnego ruchu → początek z typowego czasu reakcji, próba oznaczona jako słaba.
- Spoczynek: baseline + okna tuż przed sygnałem bez ruchu głowy.
- Walidacja: leave-one-person-out oraz leave-one-session-out; okna jednej próby nigdy po obu stronach.
- Progi klas z prawdopodobieństw w oknach tła osób spoza treningu.
- Raport: `models/gestures_report.json` (ostatni wynik + `history`).
- Trening zapisuje do `models/gestures_candidate.joblib`; podmiana `gestures.joblib` po zgodzie.

## Zostawione budującemu
Dobór cech i klasyfikatora, sposób wykrywania początku ruchu, wagi okien — według wyniku walidacji.
