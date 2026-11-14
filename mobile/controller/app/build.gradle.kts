import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "pl.halorush.controller"
    compileSdk = 36
    defaultConfig {
        applicationId = "pl.halorush.controller"
        minSdk = 24
        targetSdk = 36
        versionCode = 4
        versionName = "0.4.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
        unitTests.all { it.systemProperty("halo.previewDir", layout.buildDirectory.dir("reports/pad-preview").get().asFile.absolutePath) }
    }
}
kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_11) } }

dependencies {
    implementation(files(
        "../../BrainAccessKit-2.3.1/libs/protocol-2.3.1.jar",
        "../../BrainAccessKit-2.3.1/libs/core-release.aar",
        "../../BrainAccessKit-2.3.1/libs/transport-android-release.aar",
    ))
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("no.nordicsemi.android:ble:2.9.0")
    implementation("no.nordicsemi.android:ble-ktx:2.9.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("org.robolectric:robolectric:4.14.1")
}
