package dev.aster.rosytalkbridge

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BridgeActivitySanitizerTest {
    @Test
    fun redactsBearersLongSecretsAndUrlSuffixes() {
        val token = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        val sanitized = BridgeActivitySanitizer.sanitize(
            "Bearer $token at ws://192.168.1.25:8787/phone?token=$token#fragment",
        )

        assertFalse(sanitized.contains(token))
        assertFalse(sanitized.contains("?token="))
        assertFalse(sanitized.contains("fragment"))
        assertTrue(sanitized.contains("Bearer [redacted]"))
    }

    @Test
    fun boundsAndFlattensRecordedMessages() {
        val sanitized = BridgeActivitySanitizer.sanitize("first\nsecond\t" + "x".repeat(500))
        assertFalse(sanitized.contains('\n'))
        assertFalse(sanitized.contains('\t'))
        assertTrue(sanitized.length <= 180)
    }
}
