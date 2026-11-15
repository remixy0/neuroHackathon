import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.neurotec.minimalgui"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.neurotec.minimalgui"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "2.3.1"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_11)
    }
}

dependencies {
    // BrainAccessKit SDK artifacts live in app/libs/ (populated in the distribution zip):
    //   protocol-<ver>.jar, core-release.aar, transport-android-release.aar  (required)
    //   lsl-release.aar + liblsl-Java-release.aar                            (only if you use LSL)
    // The loose .aar/.jar carry NO dependency metadata, so declare the external deps yourself.
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.aar", "*.jar"))))
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("no.nordicsemi.android:ble:2.9.0")
    implementation("no.nordicsemi.android:ble-ktx:2.9.0")
}
