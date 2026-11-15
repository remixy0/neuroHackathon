# HALO RUSH — protokół WebSocket

Dokument opisuje aktualną implementację frontendu w `src/main.js` i `src/engine.js`.

## 1. Architektura

```text
HALO gracza 1 → rozpoznawanie gestów ─┐
                                    ├→ backend: serwer WebSocket
HALO gracza 2 → rozpoznawanie gestów ─┘              │
                                                  │ tekstowe wiadomości JSON
                                                  ▼
                                   przeglądarka: klient WebSocket
                                       ├→ lewy tor: gracz 1
                                       └→ prawy tor: gracz 2
```

- Backend uruchamia **zwykły serwer WebSocket**, nie Socket.IO.
- Przeglądarka inicjuje **jedno połączenie dla obu graczy**.
- Domyślny adres: `ws://localhost:8765`. Port i ścieżkę można zmienić w panelu „Połączenie”.
- Backend przypisuje urządzenia do graczy. Frontend nie wykrywa urządzeń i nie odbiera surowego EEG.
- Komunikacja aplikacyjna jest obecnie jednostronna: **backend → gra**. Gra nie wysyła subskrypcji, potwierdzeń, wyniku, informacji o starcie ani stanu rundy.
- Nie ma wymaganego subprotokołu WebSocket ani dodatkowego handshake'u JSON. Po standardowym otwarciu WebSocket serwer może wysyłać komendy.

`localhost` oznacza komputer, na którym działa przeglądarka. Jeśli backend działa na innym komputerze, wpisz jego osiągalny adres, np. `ws://192.168.1.20:8765`. Backend musi wtedy nasłuchiwać na odpowiednim interfejsie. Gra otwarta po HTTPS wymaga `wss://`; aktualny frontend blokuje w takim przypadku `ws://`.

## 2. Format wiadomości

**Jedna wiadomość tekstowa WebSocket = jeden obiekt JSON = jedna komenda jednego gracza.**

Minimalna poprawna wiadomość:

```json
{"player":1,"direction":"left"}
```

Zalecany format:

```json
{"type":"input","player":1,"direction":"left","id":"session-a:123"}
```

| Pole | Wymagane | Format i znaczenie |
| --- | --- | --- |
| `player` | Tak | Liczba całkowita `1` lub `2`. Nie string `"1"`, nie indeks `0`. |
| `direction` | Tak | Jedna z komend opisanych poniżej; małe litery. |
| `type` | Nie | Jeśli występuje, musi mieć dokładną wartość `"input"`. |
| `id` | Nie | Zalecany string lub liczba, unikalne dla zdarzenia danego gracza. Służy do odrzucania duplikatów. |

Dodatkowe pola, np. `confidence`, `timestamp` czy `device_id`, są ignorowane. Frontend nie stosuje progu pewności ani kontroli wieku wiadomości. Nie przesyłaj tablic komend, binarnych ramek ani kilku obiektów JSON sklejonych w jednej wiadomości. Zwykły strumień JSONL z programu Python trzeba zamienić na osobne wiadomości WebSocket.

## 3. Komendy i działanie gry

| `direction` | Akceptowane aliasy | Akcja |
| --- | --- | --- |
| `left` | `lewo` | Przesunięcie docelowego pasa o jeden w lewo. |
| `right` | `prawo` | Przesunięcie docelowego pasa o jeden w prawo. |
| `up` | `gora`, `góra` | Skok. |
| `down` | `dol`, `dół` | Ślizg. |

Zalecamy angielskie wartości dla jednolitego kontraktu backendu.

- Są trzy pasy. Dalszy ruch poza skrajny pas nie ma efektu.
- Skok i ślizg trwają po **0,95 sekundy czasu gry**.
- Podczas skoku lub ślizgu kolejne `up`/`down` są ignorowane. Nie są odkładane na później.
- Zmiana pasa jest możliwa również podczas skoku lub ślizgu.
- Nie ma komendy `neutral`, `release`, `stop`, `start`, `pause` ani sterowania kątem wychylenia.
- Gest fizyczny nie musi odpowiadać nazwie kierunku. Backend może np. zamienić rozpoznane zmarszczenie czoła na `up`.

Przykładowe **cztery osobne wiadomości**:

```json
{"type":"input","player":1,"direction":"left","id":"session-a:1"}
```

```json
{"type":"input","player":2,"direction":"right","id":"session-a:2"}
```

```json
{"type":"input","player":1,"direction":"up","id":"session-a:3"}
```

```json
{"type":"input","player":2,"direction":"down","id":"session-a:4"}
```

Dwa zdarzenia dla różnych graczy można wysłać bezpośrednio jedno po drugim przez ten sam socket.

## 4. Gest jest zdarzeniem, nie utrzymywanym stanem

Backend odpowiada za filtrowanie rozpoznania, dobór progu pewności i eliminowanie powtórzeń.

Przykład prawidłowej sekwencji:

```text
spoczynek → wykrycie gestu w lewo → wyślij raz `left`
          → gest nadal trwa      → nic nie wysyłaj
          → powrót do spoczynku  → uzbrój detektor ponownie
          → nowy gest w lewo    → wyślij nowe `left` z nowym id
```

Nie wysyłaj `left` co 250 ms tylko dlatego, że klasyfikator nadal widzi wychylenie w lewo. Każda nowa komenda może przesunąć postać o kolejny pas. Frontend nie ma debounce'u czasowego dla kierunków. Powrót głowy do środka nie powinien być interpretowany jako gest przeciwny.

Zalecenie implementacyjne: osobna maszyna stanów dla każdego gracza, uzbrajana po stabilnym spoczynku. Długość wymaganego spoczynku, progi pewności i czas blokady należy dobrać z pomiarów — protokół nie narzuca tych wartości.

## 5. Identyfikatory i duplikaty

- Deduplikacja dotyczy pary `(player, id)`. Identyczne `id` u dwóch różnych graczy nie kolidują.
- Frontend przechowuje ostatnie **1000 par łącznie**, nie 1000 na gracza.
- Ponowne odebranie zapamiętanej pary jest ignorowane, nawet jeśli ma inny kierunek.
- Bez `id` każda wiadomość jest traktowana jako nowe zdarzenie.
- Liczba `123` i string `"123"` to różne identyfikatory. Zachowaj jeden format.
- Lista jest zachowywana przez automatyczne reconnecty oraz nowe rundy.
- Lista jest czyszczona po ręcznym kliknięciu „Połącz” oraz po przeładowaniu strony.
- Identyfikator jest zapamiętywany **także wtedy, gdy komenda przyjdzie podczas pauzy lub odliczania** i nie wykona akcji.

Używaj UUID lub prefiksu sesji backendu i rosnącego licznika, np. `"boot-2026-11-14-a:123"`. Po restarcie backendu zmień prefiks. Nie odtwarzaj zaległych gestów po przywróceniu połączenia. To sterowanie na żywo, nie kolejka zadań. Deduplikacja jest ograniczona i nie stanowi gwarancji wykonania dokładnie raz.

## 6. Stan rundy i połączenia

Komendy zmieniają stan postaci tylko podczas aktywnego biegu:

| Sytuacja | Zachowanie |
| --- | --- |
| Ekran startowy lub odliczanie | Komendy odrzucane. |
| Aktywny bieg | Komendy wykonywane zgodnie z regułami ruchu. |
| Pauza | Komendy odrzucane. |
| Gracz wyeliminowany | Brak dalszych akcji jego postaci. |
| Koniec rundy | Komendy odrzucane. |

Komendy odrzucone nie są buforowane. Backend nie dostaje informacji, czy komenda wykonała akcję. Wskaźnik ostatniego kierunku w UI pokazuje odebrane wejście podczas biegu, a nie potwierdzenie wykonanego ruchu.

Po nieoczekiwanym zamknięciu socketu:

1. Gra pauzuje aktywny bieg lub odliczanie.
2. Klient próbuje połączyć się ponownie po 1, 2, 4, 8, następnie co 10 sekund przy kolejnych nieudanych próbach. Udane otwarcie resetuje licznik opóźnienia.
3. Po odzyskaniu połączenia użytkownik ręcznie wznawia grę.

Ręczne „Rozłącz” wyłącza reconnect i przełącza status na tryb klawiatury. Otwarcie panelu „Połączenie” samo pauzuje aktywną rundę. Odświeżenie strony zachowuje zapisany adres serwera, ale wymaga ponownego kliknięcia „Połącz”. Klawiatura działa również podczas połączenia WebSocket.

Frontend nie ma aplikacyjnego heartbeat ani limitu czasu ciszy. Sam brak wiadomości nie powoduje pauzy. Serwer może używać standardowych ramek WebSocket ping/pong do wykrywania zerwanego transportu; nie wysyłaj w tym celu komend ruchu.

## 7. Podłączenie i test bez HALO

W katalogu `game/`:

```sh
npm install
npm run dev
```

W drugim terminalu, również w `game/`:

```sh
npm run mock
```

Następnie:

1. Otwórz adres gry wypisany przez Vite.
2. Rozpocznij pojedynek, otwórz „Połączenie” i wpisz `ws://localhost:8765`.
3. Kliknij „Połącz”; oczekiwany status: `HALO · POŁĄCZONO`.
4. Zamknij panel i wznów grę. Poczekaj na koniec odliczania, jeśli jeszcze trwa.
5. W terminalu mocka wpisuj np. `1 left`, `2 right`, `1 up`, `2 down`, każdorazowo zatwierdzając Enterem.
6. Sprawdź, że komendy dotyczą właściwych torów.
7. Zatrzymaj mock przez Ctrl+C — gra powinna przejść w pauzę i ponawiać połączenie.

Mock jest w `mock-server.js` i nasłuchuje tylko na `127.0.0.1`. Zastąp go właściwym backendem; nie uruchamiaj obu serwerów na tym samym porcie.

## 8. Obowiązki właściwego backendu

- Utrzymywać stałe przypisanie urządzenie → `player` 1/2.
- Zamieniać rozpoznane gesty na cztery kierunki i wysyłać wyłącznie nowe zdarzenia.
- Serializować obiekt do tekstu JSON i wysłać go jako jedną wiadomość WebSocket.
- Obsługiwać rozłączenie klienta bez zatrzymania rozpoznawania sygnałów.
- Nie wysyłać backlogu gestów po reconnect.
- W środowisku innym niż lokalny mock zadbać o dostęp do serwera, kontrolę `Origin` i ewentualne TLS. Aktualny frontend nie implementuje logowania, tokenów ani własnych nagłówków autoryzacyjnych.

Obecne `tools/live.py --json` daje wyjście rozpoznawania, a nie powyższy protokół WebSocket. Potrzebny jest adapter backendowy; samo uruchomienie tego programu nie podłączy gry.
