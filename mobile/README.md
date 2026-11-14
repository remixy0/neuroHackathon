# HALO Controller / Android

Natywna aplikacja Kotlin w `controller/`: HALO → BLE → telefon → WebSocket →
istniejący backend. Model i komendy gry pozostają po stronie backendu.
Kontrakt do zaimplementowania po jego stronie: [WEBSOCKET.md](WEBSOCKET.md).

## Uruchomienie

1. Otwórz katalog `mobile/controller` jako projekt w Android Studio.
2. Użyj JDK 17+ oraz Android SDK 36. Gradle Wrapper jest w projekcie.
3. Podłącz fizyczny telefon z Androidem 7.0+ (API 24+) i Bluetooth LE.
4. Zbuduj i zainstaluj aplikację:

   ```sh
   cd mobile/controller
   ./gradlew assembleDebug
   ./gradlew installDebug
   ```

5. Wpisz URL istniejącego backendu, np. `ws://192.168.1.20:8765/ws/controller`.
   `localhost` w telefonie oznacza telefon, nie komputer z backendem.
   Serwer musi być dostępny z sieci telefonu i obsługiwać kontrakt v1.
6. Opcjonalnie wpisz token Bearer. Wybierz gracza 1 lub 2.
7. Włącz HALO, wybierz „Szukaj HALO”, udziel zgód i wybierz właściwą opaskę
   z listy. Na Androidzie 11 i starszym włącz także usługi lokalizacji.
8. Po potwierdzeniu `ready` zobaczysz stan transmisji, kontakt elektrod, baterię,
   liczniki oraz ostatnią komendę, jeśli backend wysyła jej kopię do telefonu.

Adres i gracz są zapamiętywani lokalnie; token nie jest zapisywany na dysku.
Jeden telefon obsługuje jedną opaskę; drugi gracz używa drugiego telefonu.
Przykład producenta w `BrainAccessKit-2.3.1/Examples` pozostaje niezmieniony.
Aplikacja korzysta z trzech lokalnych bibliotek SDK (bez LSL) z `BrainAccessKit-2.3.1/libs`.

## Zakres pierwszej wersji

- Działa na otwartym ekranie aplikacji; ekran pozostaje włączony podczas sesji.
- Wyjście do innej aplikacji, zablokowanie telefonu lub obrót ekranu zatrzymują
  strumień i rozłączają HALO. Brak usługi działającej w tle w tej wersji.
- Awaria WebSocket uruchamia ponowienie z nową sesją, bez zaległych próbek.
- Zerwanie BLE / brak danych wymaga ponownego wyboru opaski.
- Wysyłany jest surowy sygnał w jednostkach SDK; brak modelu na telefonie.
- HALO V1/V2 nie ma IMU wymaganego przez obecny model w `tools`. Backend musi
  zweryfikować `has_accel` / `has_gyro` i odrzucić niezgodną konfigurację.
- `ws://` jest włączone dla lokalnego demo; można używać `wss://` ze standardowym
  zaufanym certyfikatem. Nie ma obchodzenia walidacji TLS.

## Testy

```sh
cd mobile/controller
./gradlew testDebugUnitTest lintDebug assembleDebug
```

Testy JVM sprawdzają układ i walidację próbek, dokładność liczników, `null` dla
nieobecnego czujnika oraz rzeczywistą komunikację WebSocket przez MockWebServer:
hello/ready, samples/ack, komendę, stop, złą sesję i brak ACK. Serwer w testach
jest wyłącznie atrapą testową, nie nowym backendem aplikacji.

Test na sprzęcie: sprawdź osobno kontakt elektrod, wyłączenie HALO/Bluetooth,
utratę Wi-Fi, odrzucenie zajętego gracza, brak ACK, powrót połączenia i opuszczenie
aplikacji. Potwierdź po stronie backendu, że reconnect resetuje stan modelu oraz
że komenda trafia do właściwego gracza tylko raz na gest.

Licencja i informacje SDK: `BrainAccessKit-2.3.1/LICENSE.md` oraz
`BrainAccessKit-2.3.1/THIRD-PARTY-NOTICES.md`.
