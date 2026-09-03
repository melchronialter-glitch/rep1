package dev.aster.rosytalkbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ComposerVerificationPolicyTest {
    @Test
    fun delayedComposerPropagationDoesNotBecomeReadyBeforeExactTextAppears() {
        val requested = "I'm here, Lila. Directly this time. 💜"
        val observations = listOf("", "", requested)

        val decisions = observations.mapIndexed { index, observed ->
            ComposerVerificationPolicy.decide(
                observedText = observed,
                requestedText = requested,
                originalDraft = "",
                attempt = index + 1,
            )
        }

        assertEquals(
            listOf(
                ComposerVerificationDecision.RETRY,
                ComposerVerificationDecision.RETRY,
                ComposerVerificationDecision.READY,
            ),
            decisions,
        )
        assertEquals(1, decisions.count { it == ComposerVerificationDecision.READY })
    }

    @Test
    fun unchangedOriginalDraftRetriesUntilTheBoundThenRejects() {
        val decisions = (1..ComposerVerificationPolicy.MAX_ATTEMPTS).map { attempt ->
            ComposerVerificationPolicy.decide(
                observedText = "",
                requestedText = "requested text",
                originalDraft = "",
                attempt = attempt,
            )
        }

        assertEquals(
            List(ComposerVerificationPolicy.MAX_ATTEMPTS - 1) {
                ComposerVerificationDecision.RETRY
            } + ComposerVerificationDecision.REJECT,
            decisions,
        )
    }

    @Test
    fun exactTextWinsEvenOnTheFinalAttempt() {
        (1..ComposerVerificationPolicy.MAX_ATTEMPTS).forEach { attempt ->
            assertEquals(
                ComposerVerificationDecision.READY,
                ComposerVerificationPolicy.decide(
                    observedText = "exact\ntext ",
                    requestedText = "exact\ntext ",
                    originalDraft = "",
                    attempt = attempt,
                ),
            )
        }
    }

    @Test
    fun partialNormalizedOrUserEditedTextRejectsImmediately() {
        val requested = "café\nsecond line "
        val unsafeObservations = listOf(
            "caf",
            "café\nsecond line",
            "cafe\u0301\nsecond line ",
            "user text",
        )

        unsafeObservations.forEach { observed ->
            assertEquals(
                ComposerVerificationDecision.REJECT,
                ComposerVerificationPolicy.decide(
                    observedText = observed,
                    requestedText = requested,
                    originalDraft = "",
                    attempt = 1,
                ),
            )
        }
    }

    @Test
    fun retryDelaysAccumulateToTheBoundedVerificationSchedule() {
        val expectedDeltas = listOf(50L, 50L, 100L, 150L, 200L, 250L, 400L)
        val expectedOffsets = listOf(50L, 100L, 200L, 350L, 550L, 800L, 1_200L)
        val actualDeltas = (1..ComposerVerificationPolicy.MAX_ATTEMPTS)
            .map(ComposerVerificationPolicy::delayBeforeAttempt)
        var elapsed = 0L
        val actualOffsets = actualDeltas.map { delay ->
            elapsed += delay
            elapsed
        }

        assertEquals(expectedDeltas, actualDeltas)
        assertEquals(expectedOffsets, actualOffsets)
    }

    @Test
    fun elapsedDeadlineFailsClosedAfterTheLocalVerificationBudget() {
        val startedAt = 10_000L

        assertTrue(ComposerVerificationPolicy.isWithinDeadline(startedAt, startedAt))
        assertTrue(
            ComposerVerificationPolicy.isWithinDeadline(
                startedAt,
                startedAt + ComposerVerificationPolicy.MAX_ELAPSED_MS,
            ),
        )
        assertFalse(
            ComposerVerificationPolicy.isWithinDeadline(
                startedAt,
                startedAt + ComposerVerificationPolicy.MAX_ELAPSED_MS + 1L,
            ),
        )
        assertFalse(ComposerVerificationPolicy.isWithinDeadline(startedAt, startedAt - 1L))
    }

    @Test
    fun restorationOnlyOverwritesTheKnownInjectedDraft() {
        assertEquals(
            ComposerRestoreDecision.ALREADY_RESTORED,
            ComposerVerificationPolicy.restoreDecision(
                currentText = "",
                injectedText = "injected text",
                originalDraft = "",
            ),
        )
        assertEquals(
            ComposerRestoreDecision.RESTORE_INJECTED,
            ComposerVerificationPolicy.restoreDecision(
                currentText = "injected text",
                injectedText = "injected text",
                originalDraft = "",
            ),
        )
        listOf("user text", "injected text plus user edit", "injected").forEach { current ->
            assertEquals(
                ComposerRestoreDecision.LEAVE_USER_EDIT,
                ComposerVerificationPolicy.restoreDecision(
                    currentText = current,
                    injectedText = "injected text",
                    originalDraft = "",
                ),
            )
        }
    }

    @Test
    fun attemptsOutsideTheBoundAreRejected() {
        listOf(0, ComposerVerificationPolicy.MAX_ATTEMPTS + 1).forEach { attempt ->
            assertThrows(IllegalArgumentException::class.java) {
                ComposerVerificationPolicy.delayBeforeAttempt(attempt)
            }
            assertThrows(IllegalArgumentException::class.java) {
                ComposerVerificationPolicy.decide(
                    observedText = "",
                    requestedText = "requested text",
                    originalDraft = "",
                    attempt = attempt,
                )
            }
        }
    }
}
