# Testowy odbiornik HALO

Odbiera i wypisuje pełne wiadomości JSON (w tym EEG, akcelerometr, żyroskop).
Odpowiada `ready` na `hello` i `ack` na każdy pakiet `samples` lub zdarzenie `manual`, zgodnie z
kontraktem aplikacji Android. Nie uruchamia modelu ani nie wysyła ruchów do gry.
Przyjmuje też opaski bez IMU, ponieważ służy wyłącznie do testowania transmisji.

Wymagany Node.js 20+:

```sh
cd mobile/test-server
npm install
npm start
```

Serwer nasłuchuje na wszystkich interfejsach na porcie **8766** (osobnym od
mocka gry). Przy starcie wypisuje aktualne adresy komputera. W telefonie:

1. Połącz telefon i komputer z tą samą siecią Wi-Fi.
2. Wpisz wypisany adres `ws://ADRES_KOMPUTERA:8766/ws/controller`.
3. Pole tokenu pozostaw puste. Wybierz gracza, wyszukaj HALO i połącz opaskę.
4. W terminalu zobaczysz `[READY]`, następnie `[RX]` z danymi oraz `[ACK]`
   z rosnącym licznikiem odebranych próbek. W aplikacji licznik wysłanych próbek
   powinien rosnąć. Brak komend w aplikacji jest oczekiwany dla tego serwera.

**Test bez HALO:** w formularzu aplikacji wybierz „Kontroler ręczny · bez opaski”.
Po połączeniu naciśnij dowolny przycisk pada. Terminal wypisze pełny JSON `[RX]`
oraz np. `[MANUAL] gracz=1, przycisk=left, id=<session_id>:0`. Serwer potwierdza
odbiór przez `ack`; nie uruchamia gry ani nie nadaje przyciskom dodatkowego znaczenia.
Zmiana gracza na padzie otwiera nową sesję. Sesje HALO i manual mogą działać
jednocześnie dla różnych graczy. Ten sam gracz pozostaje zarezerwowany dla jednej sesji.

Przyciski: `up`, `down`, `left`, `right`, `a`, `b`, `x`, `select`, `start`.
Jedno stuknięcie = jedno `manual` z `action: "press"`, rosnącym `seq` i unikalnym `id`.
Brak klikania nie rozłącza pada: aplikacja wysyła WebSocket ping co 5 s.
Format wiadomości: [kontrakt, sekcja 7](../WEBSOCKET.md#7-kontroler-ręczny-manual).

Możesz wcześniej otworzyć `http://ADRES_KOMPUTERA:8766/health` w przeglądarce
telefonu. Odpowiedź `{"status":"ok",...}` potwierdza dostępność sieciową bez HALO.
Jeśli brak odpowiedzi, sprawdź adres, zaporę macOS (zezwól Node na połączenia
przychodzące) i izolację urządzeń w Wi-Fi. `localhost` w telefonie nie wskazuje
komputera. Alternatywnie połącz oba urządzenia z hotspotem.

Zmiana portu: `PORT=9000 npm start`. Zatrzymanie: Ctrl+C.
Serwer jest przeznaczony do lokalnego testu, nie ma uwierzytelniania; tokeny
nie są wymagane ani sprawdzane. Nie zapisuje danych do bazy ani plików.

Testy automatyczne (nie wymagają HALO):

```sh
npm test
```
