package dev.aster.rosytalkbridge

import android.os.Build
import java.net.InetAddress
import java.net.URI
import java.util.Locale

internal data class DeviceBuildInfo(
    val fingerprint: String,
    val model: String,
    val manufacturer: String,
    val brand: String,
    val device: String,
    val product: String,
    val hardware: String,
)

internal fun currentDeviceBuildInfo(): DeviceBuildInfo = DeviceBuildInfo(
    fingerprint = Build.FINGERPRINT.orEmpty(),
    model = Build.MODEL.orEmpty(),
    manufacturer = Build.MANUFACTURER.orEmpty(),
    brand = Build.BRAND.orEmpty(),
    device = Build.DEVICE.orEmpty(),
    product = Build.PRODUCT.orEmpty(),
    hardware = Build.HARDWARE.orEmpty(),
)

internal fun isProbablyEmulator(info: DeviceBuildInfo = currentDeviceBuildInfo()): Boolean {
    val fingerprint = info.fingerprint.lowercase(Locale.ROOT)
    val model = info.model.lowercase(Locale.ROOT)
    val manufacturer = info.manufacturer.lowercase(Locale.ROOT)
    val brand = info.brand.lowercase(Locale.ROOT)
    val device = info.device.lowercase(Locale.ROOT)
    val product = info.product.lowercase(Locale.ROOT)
    val hardware = info.hardware.lowercase(Locale.ROOT)
    return fingerprint.startsWith("generic") ||
        fingerprint.contains("emulator") ||
        fingerprint.contains("vbox") ||
        model.contains("google_sdk") ||
        model.contains("emulator") ||
        model.contains("android sdk built for") ||
        model.contains("sdk_gphone") ||
        manufacturer.contains("genymotion") ||
        (brand.startsWith("generic") && device.startsWith("generic")) ||
        product.contains("sdk_gphone") ||
        product.contains("vbox") ||
        hardware.contains("goldfish") ||
        hardware.contains("ranchu") ||
        hardware.contains("vbox")
}

/** Parsed relay addresses contain no user info, query, or fragment and can be logged safely. */
internal data class RelayEndpoint(
    val webSocketUrl: String,
    val healthUrl: String,
    val displayEndpoint: String,
    val host: String,
) {
    companion object {
        private const val PHONE_PATH = "/phone"
        private const val HEALTH_PATH = "/healthz"
        const val EMULATOR_HOST = "10.0.2.2"

        fun freshInstallDefault(debugBuild: Boolean, emulator: Boolean): String =
            if (debugBuild && emulator) "ws://$EMULATOR_HOST:8787$PHONE_PATH" else ""

        fun guidance(debugBuild: Boolean, emulator: Boolean): String = when {
            debugBuild && emulator ->
                "Android emulator: 10.0.2.2 reaches the computer running the relay."
            debugBuild ->
                "Physical phone: enter the exact ws://<laptop-private-ip>:8787/phone URL printed by the Windows launcher. 10.0.2.2 works only in the Android emulator."
            else ->
                "Physical phone release build: enter a configured wss:// relay URL ending in /phone. Plain ws:// is accepted only by the debug build on a trusted private network."
        }

        fun impossibleHostMessage(rawUrl: String, emulator: Boolean): String? {
            val host = try {
                URI(rawUrl.trim()).host?.lowercase(Locale.ROOT)
            } catch (_: Exception) {
                null
            } ?: return null
            return impossibleHostMessageForHost(host, emulator)
        }

        fun parse(rawUrl: String, debugBuild: Boolean, emulator: Boolean): RelayEndpoint {
            val uri = try {
                URI(rawUrl.trim())
            } catch (_: Exception) {
                throw IllegalArgumentException("Relay URL is invalid")
            }
            val scheme = uri.scheme?.lowercase(Locale.ROOT)
            if (scheme != "ws" && scheme != "wss") {
                throw IllegalArgumentException("Relay URL must use ws:// or wss://")
            }
            if (!debugBuild && scheme != "wss") {
                throw IllegalArgumentException("Release builds require a wss:// relay URL")
            }
            val host = uri.host?.lowercase(Locale.ROOT)
                ?: throw IllegalArgumentException("Relay URL must contain only a host, port, and /phone path")
            if (host.isBlank() || uri.userInfo != null || uri.query != null || uri.fragment != null) {
                throw IllegalArgumentException("Relay URL must contain only a host, port, and /phone path")
            }
            if (uri.port != -1 && uri.port !in 1..65535) {
                throw IllegalArgumentException("Relay URL port must be between 1 and 65535")
            }
            val path = uri.path.orEmpty()
            if (path.isNotEmpty() && path != "/" && path != PHONE_PATH && path != "$PHONE_PATH/") {
                throw IllegalArgumentException("Relay URL path must be /phone")
            }
            impossibleHostMessageForHost(host, emulator)?.let { throw IllegalArgumentException(it) }

            return try {
                val webSocketUrl = URI(scheme, null, host, uri.port, PHONE_PATH, null, null)
                    .toASCIIString()
                val healthScheme = if (scheme == "wss") "https" else "http"
                val healthUrl = URI(healthScheme, null, host, uri.port, HEALTH_PATH, null, null)
                    .toASCIIString()
                val displayEndpoint = URI(scheme, null, host, uri.port, null, null, null)
                    .toASCIIString()
                    .removeSuffix("/")
                RelayEndpoint(webSocketUrl, healthUrl, displayEndpoint, host)
            } catch (_: Exception) {
                throw IllegalArgumentException("Relay URL is invalid")
            }
        }

        private fun impossibleHostMessageForHost(host: String, emulator: Boolean): String? {
            val normalized = host
                .lowercase(Locale.ROOT)
                .removePrefix("[")
                .removeSuffix("]")
                .trimEnd('.')
            val numericAddress = if (
                normalized.contains(':') ||
                normalized.all { character -> character.isDigit() || character == '.' }
            ) {
                try {
                    InetAddress.getByName(normalized)
                } catch (_: Exception) {
                    null
                }
            } else {
                null
            }
            return when {
                !emulator &&
                    (normalized == EMULATOR_HOST || numericAddress?.hostAddress == EMULATOR_HOST) ->
                    "10.0.2.2 is the Android emulator host alias. On this physical phone, use the laptop private IPv4 URL printed by the Windows launcher."
                normalized == "localhost" || numericAddress?.isLoopbackAddress == true ->
                    "That relay host points back to this Android device. Use the laptop private IPv4 URL printed by the Windows launcher."
                numericAddress?.isAnyLocalAddress == true ->
                    "A wildcard listen address cannot be used as the phone relay destination. Use the laptop private IPv4 URL printed by the Windows launcher."
                else -> null
            }
        }
    }
}
