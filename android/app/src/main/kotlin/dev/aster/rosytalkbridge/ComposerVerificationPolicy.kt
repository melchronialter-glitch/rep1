package dev.aster.rosytalkbridge

/**
 * Decides whether an asynchronously updated accessibility composer is safe to submit.
 *
 * ACTION_SET_TEXT only reports that Android accepted the action. Some apps publish the resulting
 * node text on a later main-loop turn, so the original draft is retryable for a short bounded
 * interval. Any third value may be a user edit and is rejected immediately.
 */
internal object ComposerVerificationPolicy {
    private val ATTEMPT_OFFSETS_MS = longArrayOf(50L, 100L, 200L, 350L, 550L, 800L, 1_200L)
    const val MAX_ELAPSED_MS = 1_500L
    val MAX_ATTEMPTS: Int = ATTEMPT_OFFSETS_MS.size

    /** Handler posts are minimum delays; this absolute bound prevents a late main-loop send. */
    fun isWithinDeadline(startedAtElapsedMs: Long, nowElapsedMs: Long): Boolean =
        nowElapsedMs >= startedAtElapsedMs &&
            nowElapsedMs - startedAtElapsedMs <= MAX_ELAPSED_MS

    /** Delay from the previous attempt (or ACTION_SET_TEXT for attempt one). */
    fun delayBeforeAttempt(attempt: Int): Long {
        require(attempt in 1..MAX_ATTEMPTS)
        val index = attempt - 1
        return if (index == 0) {
            ATTEMPT_OFFSETS_MS[index]
        } else {
            ATTEMPT_OFFSETS_MS[index] - ATTEMPT_OFFSETS_MS[index - 1]
        }
    }

    fun decide(
        observedText: String,
        requestedText: String,
        originalDraft: String,
        attempt: Int,
    ): ComposerVerificationDecision {
        require(attempt in 1..MAX_ATTEMPTS)
        return when {
            observedText == requestedText -> ComposerVerificationDecision.READY
            observedText == originalDraft && attempt < MAX_ATTEMPTS ->
                ComposerVerificationDecision.RETRY
            else -> ComposerVerificationDecision.REJECT
        }
    }

    fun restoreDecision(
        currentText: String,
        injectedText: String,
        originalDraft: String,
    ): ComposerRestoreDecision = when {
        currentText == originalDraft -> ComposerRestoreDecision.ALREADY_RESTORED
        currentText == injectedText -> ComposerRestoreDecision.RESTORE_INJECTED
        else -> ComposerRestoreDecision.LEAVE_USER_EDIT
    }
}

internal enum class ComposerVerificationDecision {
    READY,
    RETRY,
    REJECT,
}

internal enum class ComposerRestoreDecision {
    ALREADY_RESTORED,
    RESTORE_INJECTED,
    LEAVE_USER_EDIT,
}
