// Standalone settings for the BrainAccessKit MinimalGUI example. This project is built on its
// own (its own Gradle wrapper, shipped in the distribution zip) and is NOT part of the SDK's
// multi-module build.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "MinimalGUI"
include(":app")
