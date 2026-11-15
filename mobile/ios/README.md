# HALO Controller — Swift / iOS

Natywna aplikacja SwiftUI dla iPhone'a i iPada (iOS 16+). Projekt nie korzysta
z Kotlina ani z bibliotek Androida. Android pozostaje w `../controller`.

**Dostępny jest tryb ręczny. Bezpośrednia transmisja EEG z BrainAccess HALO
nie została zaimplementowana.** To port konfiguracji, kontrolera i transportu
WebSocket, a nie pełny zamiennik trybu HALO z Androida.

## Uruchomienie na iPhonie

1. Otwórz `HaloController.xcodeproj` w pełnym Xcode z zainstalowanym SDK iOS.
2. Wybierz schemat `HaloController`. W `Signing & Capabilities` wybierz swój Team
   i w razie potrzeby zmień identyfikator `pl.halorush.controller`.
3. Wybierz iPhone'a lub symulator i uruchom aplikację (Run).
4. Uruchom istniejący odbiornik: `cd mobile/test-server && npm install && npm start`.
5. W telefonie wpisz adres wypisany przez odbiornik, np.
   `ws://192.168.1.20:8766/ws/controller`. Telefon i komputer muszą mieć połączenie
   sieciowe; `localhost` w telefonie nie oznacza komputera. Zezwól aplikacji na
   dostęp do sieci lokalnej. Token dla testowego odbiornika pozostaw pusty.
6. Wybierz gracza → Dalej → Połącz i otwórz pada.

Przebieg: **serwer → wybór kontrolera → łączenie → pełnoekranowy pad**.
Pad działa w pionie i poziomie. Sesja należy do `ControllerModel` utrzymywanego
przez `@StateObject` w aplikacji; zmiana rozmiaru przebudowuje tylko układ pada.
A/B/X mają ten sam rozmiar i jedną literę na przycisku. Krzyżak, START i SELECT
wysyłają zdarzenia; przytrzymanie nie powtarza zdarzenia. Knob nie jest częścią
obecnego kontraktu i nie jest prezentowany jako działająca opcja.

## Sesja i dane

Transport to systemowy `URLSessionWebSocketTask`, kontrakt v1 opisany w
[WEBSOCKET.md](../WEBSOCKET.md). Backend nie wymaga zmian dla iOS.

- `hello` zawiera `mode: manual`, gracza i UUID sesji. Pad jest dostępny dopiero
  po zgodnym `ready` z serwera.
- Każde naciśnięcie wysyła `manual`, `player`, `button`, `action: press`, `seq`
  oraz `id: <session_id>:<seq>`. Numeracja zaczyna się od zera.
- Brak ACK przez 2 s kończy sesję. Ping co 5 s podtrzymuje ją przy bezczynności.
  Brak pong przez 10 s zrywa połączenie. Handshake ma limit 10 s.
- Awaria transportu uruchamia ponowienie po 1/2/4/8/10 s, zawsze z nowym UUID.
  Naciśnięcia podczas przerwy są niedostępne i nie są odtwarzane.
- Błąd protokołu lub odmowa serwera pokazuje błąd i przycisk ponowienia.
- Zmiana gracza zamyka poprzednią sesję i otwiera nową. Zakończenie, przejście
  w tło i blokada telefonu zamykają połączenie. Obrót ekranu tego nie robi.
- URL i gracz są zapamiętywani. Token pozostaje wyłącznie w pamięci aplikacji.
- `ws://` jest dozwolone przez ATS dla lokalnego demo. `wss://` korzysta ze
  standardowej walidacji certyfikatu. Projekt nie omija weryfikacji TLS.

## HALO: czego brakuje

Dostarczone w repozytorium AAR/JAR zawierają SDK dla Androida i nie można
ich załadować w iOS. [Oferta producenta](https://www.brainaccess.ai/software/)
opisuje mobilne SDK Kotlin dla Androida. Opis
[desktopowego SDK](https://www.brainaccess.ai/software/brainaccess-sdk/)
obejmuje też macOS, co nie oznacza biblioteki dla iOS.

Publiczna dokumentacja klas `PacketCodec` i `GattUuids` nie dostarcza kompletnej
specyfikacji komend konfiguracji oraz dekodowania skompresowanych pakietów EEG.
Nie zaimplementowano zgadywanego dekodera ani pozornego strumienia danych.
Do pełnego portu HALO potrzeba SDK skompilowanego dla iOS albo specyfikacji
GATT, komend start/stop, konfiguracji kanałów i formatu pakietów wraz z danymi
referencyjnymi. Sam CoreBluetooth umożliwia transport BLE, ale nie definiuje
protokołu urządzenia. Ekran wyboru kontrolera jasno pokazuje brak tego trybu.

## Sprawdzenie bez SDK iPhone'a

Pakiet SwiftPM używa tych samych plików transportu i interfejsu co projekt iOS.
Ma podgląd dla macOS i samodzielne testy, które nie wymagają XCTest ani dodatkowych
pakietów Swift:

```sh
cd mobile/ios
swift build
swift run HaloProtocolChecks
node scripts/smoke.mjs "$PWD/.build/debug/HaloSmoke"
# Opcjonalny podgląd interfejsu macOS:
swift run HaloDesktopPreview
```

Test integracyjny wymaga zainstalowanych zależności `../test-server`
(`cd ../test-server && npm install`). Uruchamia tymczasowe serwery na wolnych
portach localhost; nie dotyka działającego odbiornika na porcie 8766.

`HaloProtocolChecks` sprawdza kontrakt hello/manual, wszystkie 9 przycisków,
identyfikatory zdarzeń, adresy, błędne koperty, gracza i odrzucenie przez serwer.
`smoke.mjs` uruchamia skompilowanego klienta Swift z prawdziwym odbiornikiem Node:
11 s bezczynności (heartbeat), 9 przycisków, zmianę sesji i gracza oraz zwolnienie
slotów. Osobne serwery sprawdzają brak ACK, błędny tryb w ready, odmowę, błędny
identyfikator sesji i brak ready.

Na komputerze przygotowującym port dostępne były tylko Command Line Tools,
bez pełnego Xcode i SDK iOS. Kompilacja macOS i testy transportu nie zastępują
builda ani testu na iPhonie. Przed użyciem na urządzeniu sprawdź obrót podczas
sesji, zgodę na sieć lokalną, utratę Wi-Fi, zmianę gracza i przejście w tło.

Po instalacji Xcode można też zbudować wersję symulatora z terminala:

```sh
xcodebuild -project HaloController.xcodeproj -scheme HaloController \
  -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath DerivedData CODE_SIGNING_ALLOWED=NO build
```
