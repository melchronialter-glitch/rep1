plugins {
    id("com.android.application")
}

android {
    namespace = "dev.aster.rosytalkbridge"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.aster.rosytalkbridge"
        minSdk = 29
        targetSdk = 36
        versionCode = 2
        versionName = "0.2.0"

        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    buildTypes {
        debug {
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        release {
            isMinifyEnabled = false
            manifestPlaceholders["usesCleartextTraffic"] = "false"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
