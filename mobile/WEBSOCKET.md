# HALO Controller — kontrakt WebSocket v1

Propozycja kontraktu zaimplementowana w `controller/`. Istniejący backend musi
obsługiwać poniższe wiadomości; nie zakładamy, że już obsługuje ten format.
Nie dodajemy nowego backendu. Protokół do gry pozostaje w `../game/WEBSOCKET.md`.

```text
HALO ──BLE── Android ──WebSocket /ws/controller── istniejący backend + model
                                                      │
                          gra ◀──WebSocket input──────┘
```

## Transport i kolejność

- Zwykły WebSocket (RFC 6455), bez Socket.IO i bez subprotokołu.
- Proponowana ścieżka `/ws/controller`; pełny URL jest edytowalny w aplikacji.
- Jedna tekstowa wiadomość = jeden obiekt JSON UTF-8. Brak binarnych ramek w v1.
- Telefon wysyła opcjonalny nagłówek `Authorization: Bearer <token>` przy upgrade.
- `wss://` do połączeń szyfrowanych; `ws://` jest dostępne dla sieci lokalnej.
- Każda wiadomość w obu kierunkach zawiera `type`, `version: 1`, `session_id` (UUID).
- Jeden socket telefonu odpowiada jednej opasce i jednemu graczowi, `1` lub `2`.
- Sekwencja: otwarcie → `hello` → `ready` → `samples` / `ack` → `stop` / zamknięcie.
- Backend ma 5 s na `ready`. Próbek nie wolno wysyłać przed `ready`.
- Backend rezerwuje gracza atomowo. Drugi telefon żądający zajętego gracza otrzymuje
  `error` i zamknięcie. Nie wolno bezwarunkowo nadpisywać przypisania istniejącego gracza.
- Przy zamykaniu starego socketu backend zwalnia wyłącznie sesję będącą jego właścicielem,
  aby opóźnione zamknięcie nie usunęło nowego przypisania po reconnect.

## 1. Telefon → backend: hello

```json
{
  "type": "hello",
  "version": 1,
  "session_id": "875b11bb-dfff-477b-9237-1baf62e0908f",
  "role": "controller",
  "player": 1,
  "device": {
    "id": "opaque-sdk-device-id",
    "name": "BA HALO 208",
    "hardware": "HALO_V3",
    "sdk": "BrainAccessKit-2.3.1"
  },
  "stream": {
    "sample_rate_hz": 250,
    "channels": ["O1", "O2", "Fp2", "Fp1"],
    "layout": "sample_major",
    "eeg_unit": "uV",
    "accel_unit": "m/s2",
    "gyro_unit": "deg/s",
    "has_accel": true,
    "has_gyro": true
  }
}
```

`device.id` to nieprzezroczysty identyfikator SDK, przydatny do logowania, nie do
uwierzytelniania. Wartości `channels` pochodzą z rzeczywistego strumienia — backend
mapuje kanały po nazwach, nie po zakładanej pozycji. Metadane są stałe w sesji.
Aplikacja ustawia fabryczną konfigurację modelu: 250 Hz, wszystkie elektrody,
wyłączony pomiar impedancji. Nie wykonuje filtracji ani normalizacji sygnału.

Backend weryfikuje wersję, gracza, częstotliwość, kanały i dostępność czujników
potrzebnych modelowi. Model w `tools/neuro/pipeline.py` wymaga EEG O1/O2/Fp2/Fp1
oraz wszystkich trzech osi akcelerometru i żyroskopu. HALO V1/V2 nie zapewnia tych
czujników; backend powinien odrzucić taki strumień dla tego modelu, zamiast
podstawiać zera. Można dopuścić go dopiero z modelem obsługującym brak IMU.

## 2. Backend → telefon: ready

```json
{"type":"ready","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","player":1}
```

Wysyłane dokładnie raz, po zaakceptowaniu `hello` i przygotowaniu osobnego stanu
modelu dla sesji. `session_id` i `player` muszą odpowiadać żądaniu.

## 3. Telefon → backend: samples

Jeden pakiet SDK jest jedną wiadomością. Nie czekamy na zapełnienie okna modelu.
Przykład dwóch próbek na czterech kanałach:

```json
{
  "type": "samples",
  "version": 1,
  "session_id": "875b11bb-dfff-477b-9237-1baf62e0908f",
  "seq": 0,
  "sample_count": 2,
  "first_sample_index": "250",
  "wire_last_sample_index": "251",
  "host_time_ns": "5261234567890123",
  "eeg": [12.5, -8.1, 23.4, 19.2, 13.0, -7.8, 24.1, 18.9],
  "accel": [0.1, 0.2, 9.81, 0.1, 0.2, 9.81],
  "gyro": [0.3, -0.2, 0.0, 0.3, -0.2, 0.0],
  "is_dummy": [false, false],
  "contact": [true, true, true, true],
  "battery_pct": 87.0,
  "phone_discarded_samples": "0",
  "ble_missed_samples": "0"
}
```

| Pole | Znaczenie |
| --- | --- |
| `seq` | Liczba całkowita od 0, rośnie o 1 dla każdej wysłanej wiadomości `samples`. |
| `sample_count` | Liczba wierszy N; dodatnia liczba całkowita. |
| `first_sample_index` | Pierwszy numer próbki urządzenia, zapisany jako dziesiętny string. Początek sesji nie musi mieć indeksu 0. |
| `wire_last_sample_index` | Oryginalny licznik pakietu BLE jako string; `"-1"`, jeśli brak. Zachowany do wykrywania nieciągłości / kolejności. |
| `host_time_ns` | Monotoniczny zegar telefonu przy odebraniu pakietu BLE, jako string. Nie jest czasem Unix ani zegarem serwera. |
| `eeg` | N × C skończonych liczb, płaska tablica: próbka 0 wszystkie kanały, próbka 1 wszystkie kanały, itd. Jednostka µV. |
| `accel`, `gyro` | N × 3 liczb, kolejno x/y/z dla każdej próbki. `null` dla nieobecnego czujnika, zgodnie z `hello`. |
| `is_dummy` | N wartości bool. `true` oznacza sztuczną próbkę wstawioną przez SDK w miejsce utraconej. |
| `contact` | C wartości bool: `true` = kontakt; stan elektrod dla pakietu. |
| `battery_pct` | Liczba 0–100, `null`, jeśli SDK nie podaje poprawnej wartości. |
| `phone_discarded_samples` | String: liczba przeterminowanych próbek odrzuconych przez telefon w bieżącej sesji WebSocket. |
| `ble_missed_samples` | String: narastający licznik brakujących próbek SDK w połączeniu BLE; może przetrwać reconnect WebSocket. |

Liczby 64-bitowe zapisujemy jako stringi, aby zachować dokładność także w JavaScript.
`seq` jest zwykłym numerem JSON, ograniczonym w kontrakcie do bezpiecznych liczb
całkowitych JavaScript. Próbek nie należy sortować po czasie serwera.
SDK powtarza pojedynczy odczyt IMU pakietu przy poszczególnych próbkach EEG;
to nie oznacza niezależnego pomiaru IMU przy każdej próbce.

Backend powinien walidować długości, typy, skończoność liczb, `seq`, sesję oraz
zgodność z `hello` **przed** przekazaniem danych do modelu. Praktyczny limit
rozmiaru pojedynczej wiadomości: 1 MiB (SDK potrafi uzupełnić większą lukę BLE).
Nie wolno rozpoznawać gestów z wierszy `is_dummy=true`. Nieciągłość numeracji,
brak kontaktu lub luka powinny unieważnić okno detektora i uruchomić ponowne
zbieranie poprawnego okna; nie sklejać fragmentów odległych w czasie.

Przykład ułożenia poprawnego pakietu dla istniejącego rozpoznawania (po walidacji):

```python
eeg = np.asarray(packet["eeg"]).reshape(packet["sample_count"], len(channels))
accel = np.asarray(packet["accel"]).reshape(packet["sample_count"], 3)
gyro = np.asarray(packet["gyro"]).reshape(packet["sample_count"], 3)
names = channels + ["Accel_x", "Accel_y", "Accel_z", "Gyro_x", "Gyro_y", "Gyro_z"]
# Recognizer(names, sample_rate_hz) tworzymy raz na ciągły strumień, nie na pakiet.
chunk = np.concatenate([eeg, accel, gyro], axis=1).T  # kanały × próbki
results = recognizer.push(chunk)
```

## 4. Backend → telefon: ack

```json
{"type":"ack","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","seq":12}
```

Potwierdzenie narastające: wszystkie pakiety do `seq` włącznie zostały zwalidowane
i przyjęte do ograniczonego bufora analizy. To nie jest potwierdzenie wykonania
gestu ani ruchu w grze. Wysyłać co najwyżej co 250 ms przy napływających danych;
można potwierdzać każdy pakiet. Nie wysyłać ACK dla nieprzyjętych danych.
Powtórzony / starszy ACK jest ignorowany. ACK wykraczający poza wysłany zakres
kończy sesję błędem. Telefon nie retransmituje próbek.

Jeśli najstarszy niepotwierdzony pakiet czeka ponad 2 s lub kolejka wyjściowa
WebSocket przekroczy 64 KiB, telefon przerywa połączenie i otwiera nową sesję.
Pojedynczy pakiet może przekroczyć próg kolejki; próg jest sprawdzany przed
wysłaniem następnego. Próbki starsze niż 500 ms według zegara telefonu są
odrzucane przed wysłaniem (np. podczas oczekiwania na `ready`).
Backend również ogranicza kolejkę analizy i nie wykonuje zaległych gestów.

## 5. Backend → telefon: input (opcjonalny podgląd)

```json
{"type":"input","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","player":1,"direction":"left","id":"event-123","confidence":0.91}
```

Telefon wyświetla kierunek `left`, `right`, `up` albo `down`. `id` i `confidence`
są opcjonalne i obecnie ignorowane przez telefon. Komendy do gry backend wysyła
**bezpośrednio** do jej socketu, w istniejącym formacie:

```json
{"type":"input","player":1,"direction":"left","id":"event-123"}
```

Telefon nie rozpoznaje gestów, nie steruje lokalnie grą i nie przekazuje komend
z powrotem do backendu. Backend odpowiada za próg pewności, mapowanie gestów,
powrót do spoczynku i wysłanie pojedynczego zdarzenia na gest.

## 6. Zakończenie i błędy

Telefon wysyła best-effort `stop`, następnie WebSocket close 1000:

```json
{"type":"stop","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","reason":"user_or_lifecycle"}
```

Backend może odrzucić sesję (również przed `ready`):

```json
{"type":"error","version":1,"session_id":"875b11bb-dfff-477b-9237-1baf62e0908f","code":"unsupported_stream","message":"Ten model wymaga akcelerometru i żyroskopu HALO V3."}
```

Przykładowe kody: `unsupported_version`, `unsupported_stream`, `player_busy`,
`invalid_packet`, `unauthorized`. Wszystkie wiadomości `error` są terminalne
po stronie telefonu: pokazuje komunikat i wymaga ręcznego ponownego startu.
Nieznany typ, binarna wiadomość, zła wersja/sesja lub błędny JSON również kończą
transmisję. Dodatkowe pola znanych wiadomości są ignorowane. Backend wysyła do
telefonu małe wiadomości (maks. 16 384 znaków).

Przy awarii sieci ponowienia następują po 1, 2, 4, 8, potem co 10 s. Każde
ponowienie ma nowy UUID, nowe `hello`, nowe `seq=0` i świeży strumień HALO.
Pięć sekund wysłanych próbek resetuje opóźnienie ponawiania. Stan modelu i
detektora gestów backendu nie przechodzi pomiędzy sesjami. Brak odtwarzania
historii. Błędy 401/403/404 podczas upgrade i close 1002/1003/1008 są terminalne.

OkHttp wysyła standardowy WebSocket ping co 10 s; serwer odpowiada pong (zwykle
robi to biblioteka WebSocket). Dodatkowo backend powinien wygaszać sesję po
np. 3 s bez `samples` po fazie `ready` i zwalniać ją przy każdym disconnect.
`stop` może nie dotrzeć po utracie sieci lub zamknięciu procesu. Telefon kończy
sesję BLE, jeśli przez 8 s nie otrzyma pakietu, i wymaga ponownego wyboru HALO.

## Źródło formatu SDK

[BrainAccess EegChunk 2.3.1](https://www.brainaccess.ai/documentation/kotlin-sdk/2.3.1/_static/dokka/core/com.neurotec.brainaccess.core/-eeg-chunk/index.html)
opisuje kolejność sample-major, jednostki, zegar monotoniczny i znaczniki luk.
[Instrukcja SDK](https://www.brainaccess.ai/documentation/kotlin-sdk/2.3.1/usage.html)
opisuje konfigurację domyślną i różnice sprzętowe HALO.
