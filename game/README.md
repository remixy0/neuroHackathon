# HALO RUSH

Lokalna gra przeglądarkowa dla dwóch osób na jednym komputerze, inspirowana trójpasmowymi endless runnerami. Dwie niezależne sceny Three.js, własne proceduralne modele postaci i kolorowego miasteczka, identyczny losowany tor dla obu graczy. Nie wymaga zewnętrznych assetów ani usług. Fonty Google są opcjonalne (fallback systemowy).

## Start

W katalogu `game/` (Node.js 20.19+ lub 22.12+):

```sh
npm install
npm run dev
```

Otwórz adres wypisany przez Vite. `npm run build` tworzy statyczny katalog `dist/`; `npm test` sprawdza logikę. Gra wymaga WebGL 2. Serwer developerski domyślnie jest dostępny tylko na lokalnym komputerze.

## Zasady

90 sekund, 3 życia na gracza. Wynik = dystans × 10 (zaokrąglony w dół) + monety × 25. Wygrywa wyższy wynik. Po utracie wszystkich żyć gracz przestaje zdobywać punkty, drugi kontynuuje. Runda kończy się po czasie lub eliminacji obu graczy. Po trafieniu 1,8 s nietykalności. Przeszkody: wagon (zmiana pasa), pomarańczowa bariera (skok), fioletowa bramka (ślizg). Skok i ślizg trwają 0,95 s. Dystans to jednostki świata gry, umownie metry.

Klawiatura: gracz 1 WASD, gracz 2 strzałki; P pauzuje/wznawia. Strzałka góra/W = skok, dół/S = ślizg. Jeden nacisk = jedna komenda. Nie można skakać i ślizgać się jednocześnie. Ukrycie karty automatycznie pauzuje grę.

## WebSocket: kontrakt integracji

Pełna specyfikacja: [WEBSOCKET.md](WEBSOCKET.md).

Frontend jest **klientem**, backend serwerem. Jeden socket obsługuje obu graczy. W panelu „Połączenie” ustaw adres (domyślnie `ws://localhost:8765`) i kliknij Połącz. Pod HTTPS użyj `wss://`. Przeglądarka może wymagać zgody na dostęp do sieci lokalnej. Po utracie połączenia runda pauzuje, klient ponawia co 1–10 s; po powrocie połączenia wznowienie jest ręczne.

Każda wiadomość to pojedynczy tekstowy obiekt JSON:

```json
{"type":"input","player":1,"direction":"left","id":123}
```

- `player`: liczba **1 lub 2** (nie indeks 0/1).
- `direction`: `left`, `right`, `up`, `down`; aliasy `lewo`, `prawo`, `gora`/`góra`, `dol`/`dół`.
- `type`: opcjonalne, jeśli obecne musi być `input`.
- `id`: opcjonalny unikalny identyfikator zdarzenia; frontend deduplikuje ostatnie 1000 identyfikatorów per połączenie logiczne z uwzględnieniem gracza. Używaj UUID albo rosnącego licznika, który nie resetuje się przy automatycznym reconnect.

Backend powinien wysyłać **zbocze/zdarzenie rozpoznanego gestu**, po filtrowaniu pewności i odbić. Nie wysyłaj tej samej komendy co klatkę utrzymywanego gestu. Powrót do neutralnej pozycji nie jest komendą. Frontend nie odgaduje gestów z EEG i nie integruje bezpośrednio istniejącego `tools/live.py`. Nie buforuje komend poza aktywną rundą. Błędne wiadomości są ignorowane. Klawiatura pozostaje aktywna przy połączonym backendzie.

### Ręczny mock

W drugim terminalu `npm run mock`. Połącz grę z adresem domyślnym i rozpocznij rundę, następnie wpisuj `1 left`, `2 up` itd. Mock korzysta wyłącznie z loopbacku. Produkcyjny backend powinien osobno kontrolować Origin i dostęp.

## Struktura

- `src/engine.js`: deterministyczny generator toru, ruch, kolizje, parser protokołu.
- `src/scene.js`: renderowanie i własne modele Three.js.
- `src/main.js`: runda, UI, klawiatura i WebSocket z reconnect.
- `test/engine.test.js`: testy kontraktu i mechaniki.

Parametry czasu i szerokości pasa są w `engine.js`, tempo biegu w `main.js`. Bez danych o opóźnieniu rozpoznawania gra wymaga jeszcze strojenia z prawdziwymi urządzeniami.
