package dev.aster.rosytalkbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class RelayEndpointTest {
    @Test
    fun physicalDebugFreshInstallHasNoEmulatorAddress() {
        assertEquals("", RelayEndpoint.freshInstallDefault(debugBuild = true, emulator = false))
    }

    @Test
    fun emulatorDebugFreshInstallUsesHostAlias() {
        assertEquals(
            "ws://10.0.2.2:8787/phone",
            RelayEndpoint.freshInstallDefault(debugBuild = true, emulator = true),
        )
    }

    @Test
    fun physicalPhoneRejectsEmulatorHostWithoutErasingInput() {
        val error = expectIllegalArgument {
            RelayEndpoint.parse(
                "ws://10.0.2.2:8787/phone",
                debugBuild = true,
                emulator = false,
            )
        }
        assertTrue(error.message.orEmpty().contains("physical phone"))
    }

    @Test
    fun emulatorAcceptsHostAliasAndBuildsHealthUrl() {
        val endpoint = RelayEndpoint.parse(
            "ws://10.0.2.2:8787/",
            debugBuild = true,
            emulator = true,
        )
        assertEquals("ws://10.0.2.2:8787/phone", endpoint.webSocketUrl)
        assertEquals("http://10.0.2.2:8787/healthz", endpoint.healthUrl)
        assertEquals("ws://10.0.2.2:8787", endpoint.displayEndpoint)
    }

    @Test
    fun physicalLanUrlMapsToTokenFreeHealthEndpoint() {
        val endpoint = RelayEndpoint.parse(
            "ws://192.168.1.25:8787/phone",
            debugBuild = true,
            emulator = false,
        )
        assertEquals("http://192.168.1.25:8787/healthz", endpoint.healthUrl)
        assertFalse(endpoint.displayEndpoint.contains("phone"))
    }

    @Test
    fun secureRelayMapsToHttpsHealthEndpoint() {
        val endpoint = RelayEndpoint.parse(
            "wss://relay.example/phone",
            debugBuild = false,
            emulator = false,
        )
        assertEquals("https://relay.example/healthz", endpoint.healthUrl)
        assertEquals("wss://relay.example", endpoint.displayEndpoint)
    }

    @Test
    fun rejectsLoopbackWildcardAndQueryDestinations() {
        listOf(
            "ws://localhost:8787/phone",
            "ws://127.0.0.1:8787/phone",
            "ws://127.1:8787/phone",
            "ws://0.0.0.0:8787/phone",
            "ws://[0:0:0:0:0:0:0:1]:8787/phone",
            "ws://[0:0:0:0:0:0:0:0]:8787/phone",
            "ws://[::ffff:127.0.0.1]:8787/phone",
            "ws://192.168.1.25:8787/phone?token=secret",
        ).forEach { value ->
            expectIllegalArgument {
                RelayEndpoint.parse(value, debugBuild = true, emulator = false)
            }
        }
    }

    @Test
    fun physicalPhoneRejectsTrailingDotEmulatorAlias() {
        expectIllegalArgument {
            RelayEndpoint.parse(
                "ws://10.0.2.2.:8787/phone",
                debugBuild = true,
                emulator = false,
            )
        }
    }

    @Test
    fun releaseRejectsPlainWebSocket() {
        val error = expectIllegalArgument {
            RelayEndpoint.parse(
                "ws://192.168.1.25:8787/phone",
                debugBuild = false,
                emulator = false,
            )
        }
        assertTrue(error.message.orEmpty().contains("wss://"))
    }

    @Test
    fun emulatorDetectionUsesBuildSignalsWithoutClassifyingOrdinaryPhone() {
        assertTrue(
            isProbablyEmulator(
                buildInfo(model = "sdk_gphone64_x86_64", hardware = "ranchu"),
            ),
        )
        assertFalse(
            isProbablyEmulator(
                buildInfo(
                    fingerprint = "google/panther/panther:16/example:user/release-keys",
                    model = "Pixel 7",
                    manufacturer = "Google",
                    brand = "google",
                    device = "panther",
                    product = "panther",
                    hardware = "tensor",
                ),
            ),
        )
    }

    private fun buildInfo(
        fingerprint: String = "vendor/device/device:16/example:user/release-keys",
        model: String = "Physical phone",
        manufacturer: String = "Google",
        brand: String = "vendor",
        device: String = "device",
        product: String = "device",
        hardware: String = "hardware",
    ) = DeviceBuildInfo(fingerprint, model, manufacturer, brand, device, product, hardware)

    private fun expectIllegalArgument(block: () -> Unit): IllegalArgumentException {
        try {
            block()
            fail("Expected IllegalArgumentException")
        } catch (error: IllegalArgumentException) {
            return error
        }
        throw AssertionError("unreachable")
    }
}
