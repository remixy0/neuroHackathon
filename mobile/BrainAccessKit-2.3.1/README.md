# BrainAccessKit 2.3.1

Prebuilt Android SDK for BrainAccess EEG headsets. These artifacts are NOT published
to any Maven repository — drop them into your app and reference them directly.

## Quick links
- Website: https://www.brainaccess.ai/
- Documentation: https://www.brainaccess.ai/documentation/kotlin-sdk/2.3.1/index.html
- Changes in this release: CHANGELOG.md

## Start here
`Examples/MinimalGUI/` is a complete, buildable example app (scan -> connect ->
stream, showing contact / missed-samples / bluetooth state). Open it in Android
Studio, or `cd Examples/MinimalGUI && ./gradlew installDebug`.

## libs/
| File | Required | Purpose |
|------|----------|---------|
| protocol-2.3.1.jar          | yes          | wire codec + config (pure JVM) |
| core-release.aar               | yes          | BrainAccessClient, DeviceSession, config store, typed EEG output |
| transport-android-release.aar  | yes          | Nordic-backed BLE transport |
| lsl-release.aar                | LSL only     | Lab Streaming Layer outlet adapter |
| liblsl-Java-release.aar        | LSL only     | liblsl native library (arm64-v8a, armeabi-v7a, x86, x86_64) |

## Install (consumer module build.gradle.kts)
1. Copy everything from this `libs/` folder into your module's `libs/`.
2. Add:

       dependencies {
           implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar", "*.jar"))))

           // The loose .aar/.jar above carry NO dependency metadata, so declare these
           // yourself (Gradle resolves their transitives, including AndroidX):
           implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
           implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
           implementation("no.nordicsemi.android:ble:2.9.0")       // transport-android
           implementation("no.nordicsemi.android:ble-ktx:2.9.0")   // transport-android
           implementation("net.java.dev.jna:jna:5.14.0@aar")       // LSL only: liblsl-Java binds through JNA
       }

   Requirements: Kotlin 2.0.x, minSdk 24, compileSdk 36+, AndroidX
   (android.useAndroidX=true). Without LSL, omit lsl-release.aar +
   liblsl-Java-release.aar and the JNA line; the kotlinx/nordic deps above still apply.
   With LSL, use the JNA `@aar` variant (it carries libjnidispatch.so per ABI) — the
   plain jar has no Android natives.

## Permissions
The SDK declares the BLE permissions but NEVER requests them. Your app requests the
runtime set for the running OS (API 31+: BLUETOOTH_SCAN + BLUETOOTH_CONNECT;
API <= 30: ACCESS_FINE_LOCATION). See
com.neurotec.brainaccess.transport.BlePermissions.required.

## Quick start
       val client = BrainAccessClient(NordicTransport(context))
       scope.launch {
           val device = client.scan().first()
           val session = client.connect(device).getOrThrow()   // connects + handshake
           session.stream().collect { chunk ->
               // chunk.samples (flat µV), chunk.channels, chunk.srate, chunk.accel
           }
       }
       // optional LSL outlet:
       // session.streamToLsl(scope)   // BrainAccess Board LSL contract v1, source_id = BLE name

License: see LICENSE.md — proprietary; it grants integration into your own apps and
redistribution as an inseparable part of them, not standalone. Third-party components
redistributed in these artifacts (Nordic BLE library, liblsl / liblsl-Java) and their
notices: THIRD-PARTY-NOTICES.md.
Full API reference: the Dokka docs (Quick links).