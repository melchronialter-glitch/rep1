package dev.aster.rosytalkbridge

data class BridgeActivityEvent(
    val sequence: Long,
    val recordedAtEpochMs: Long,
    val message: String,
)

/** Defense in depth for the process-local diagnostic ring. */
internal object BridgeActivitySanitizer {
    private const val MAX_MESSAGE_CHARACTERS = 180
    private val bearerPattern = Regex("""(?i)\bBearer\s+\S+""")
    private val urlSuffixPattern = Regex("""(?i)((?:https?|wss?)://[^\s?#]+)[?#][^\s]+""")
    private val longSecretPattern = Regex("""\b[A-Za-z0-9_-]{40,}\b""")
    private val whitespacePattern = Regex("""[\r\n\t]+""")

    fun sanitize(message: String): String {
        val singleLine = whitespacePattern.replace(message, " ").trim()
        val withoutBearer = bearerPattern.replace(singleLine, "Bearer [redacted]")
        val withoutUrlSuffix = urlSuffixPattern.replace(withoutBearer) { match ->
            "${match.groupValues[1]}[redacted]"
        }
        val withoutLongSecrets = longSecretPattern.replace(withoutUrlSuffix, "[redacted-secret]")
        return withoutLongSecrets.take(MAX_MESSAGE_CHARACTERS).ifBlank { "Bridge activity" }
    }
}
