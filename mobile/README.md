# HALO Controller / Android

Natywna aplikacja Kotlin w `controller/`: HALO → BLE → telefon → WebSocket →
istniejący backend. Model i komendy gry pozostają po stronie backendu.
Kontrakt do zaimplementowania po jego stronie: [WEBSOCKET.md](WEBSOCKET.md).

Od wersji 0.3.0 dostępny jest również **kontroler ręczny**, bez HALO i bez
uprawnień Bluetooth. W formularzu serwera wybierz „Kontroler ręczny · bez opaski”
i dotknij „Dalej”. Po `hello` / `ready` pojawi się ekran retro pada:
krzyżak, A/B/X, SELECT i START. Każde stuknięcie wysyła jedno zdarzenie `manual`.
Przytrzymanie nie powtarza akcji. Zakładki GRACZ 1/2 przełączają gracza przez
zamknięcie starej i utworzenie nowej sesji. Ten sam gracz nie może równocześnie
korzystać z dwóch kontrolerów (HALO lub ręcznych).

Przy zerwaniu połączenia pad jest zastępowany ekranem łączenia; stare naciśnięcia
nie są odtwarzane. Zakończenie / Wstecz / opuszczenie aplikacji rozłączają sesję.
SELECT i START wysyłają przyciski do backendu, nie zarządzają lokalną sesją.

Do sprawdzenia połączenia bez właściwego backendu użyj
[testowego odbiornika](test-server/README.md): `cd mobile/test-server && npm install && npm start`.
Wypisuje dane w terminalu i podaje adres WebSocket do wpisania w telefonie.

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

5. **Serwer:** wpisz URL istniejącego backendu, np. `ws://192.168.1.20:8765/ws/controller`
   (dla lokalnego odbiornika testowego port `8766`).
   `localhost` w telefonie oznacza telefon, nie komputer z backendem.
   Serwer musi być dostępny z sieci telefonu i obsługiwać kontrakt v1.
6. Opcjonalnie wpisz token Bearer, wybierz gracza 1 lub 2 i dotknij „Dalej · wybierz HALO”.
7. **Opaska:** włącz HALO, wybierz „Szukaj HALO”, udziel zgód i dotknij właściwej
   opaski na liście. Na Androidzie 11 i starszym włącz także usługi lokalizacji.
8. **Łączenie:** aplikacja pokazuje postęp połączenia z HALO, serwerem i potwierdzenia
   sesji. Możesz anulować. Po błędzie dostępne jest ponowienie, wybór innej opaski
   lub zmiana serwera.
9. **Status:** po potwierdzeniu `ready` ekran automatycznie pokazuje transmisję,
   kontakt elektrod, baterię, liczniki oraz ostatnią komendę serwera. Przy zerwaniu
   WebSocket aplikacja wraca do ekranu łączenia i pokazuje ponawianie.

„Zakończ sesję” oraz systemowy przycisk Wstecz na ekranie statusu zatrzymują
transmisję i wracają do wyboru HALO. „Zmień serwer” rozłącza sesję i wraca do
formularza. Przejście wstecz zachowuje wpisany adres, gracza i token w pamięci;
token nie jest zapisywany na dysku ani w stanie odtwarzanym po obrocie ekranu.

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
- W trybie HALO wysyłany jest surowy sygnał w jednostkach SDK; brak modelu na telefonie.
- W trybie ręcznym przesyłane są zdarzenia przycisków zgodnie z sekcją `manual`
  w kontrakcie. Tryb nie wymaga opaski ani włączenia Bluetooth.
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
hello/ready, samples/ack, manual/ack, komendę, stop, złą sesję i brak ACK. Test pada
w Robolectric sprawdza rozmiary pól dotyku, brak nakładania przycisków i kliknięcia
na czterech szerokościach; podglądy zapisuje w `app/build/reports/pad-preview/`.
Serwer w testach
jest wyłącznie atrapą testową, nie nowym backendem aplikacji.

Test na sprzęcie: sprawdź osobno kontakt elektrod, wyłączenie HALO/Bluetooth,
utratę Wi-Fi, odrzucenie zajętego gracza, brak ACK, powrót połączenia i opuszczenie
aplikacji. Potwierdź po stronie backendu, że reconnect resetuje stan modelu oraz
że komenda trafia do właściwego gracza tylko raz na gest.

Licencja i informacje SDK: `BrainAccessKit-2.3.1/LICENSE.md` oraz
`BrainAccessKit-2.3.1/THIRD-PARTY-NOTICES.md`.
