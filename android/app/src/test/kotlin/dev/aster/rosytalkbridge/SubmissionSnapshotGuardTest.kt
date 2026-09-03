package dev.aster.rosytalkbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class SubmissionSnapshotGuardTest {
    @Test
    fun initialRevisionMismatchPublishesBeforeRejecting() {
        val changed = snapshot(revision = 2, eventId = "observation-2")
        val events = mutableListOf<String>()
        var published: ConversationSnapshot? = null
        val guard = SubmissionSnapshotGuard { observed ->
            published = observed
            events += "published"
        }

        val error = assertThrows(BridgeException::class.java) {
            guard.requireInitialSnapshot(
                snapshot = changed,
                expectedRevision = 1,
                expectedSnapshotId = "observation-1",
            )
        }.also { events += "rejected" }

        assertEquals(listOf("published", "rejected"), events)
        assertSame(changed, published)
        assertEquals("STALE_SNAPSHOT", error.code)
    }

    @Test
    fun revalidationRevisionMismatchPublishesBeforeRejecting() {
        val changed = snapshot(revision = 3, eventId = "observation-3")
        val events = mutableListOf<String>()
        var published: ConversationSnapshot? = null
        val guard = SubmissionSnapshotGuard { observed ->
            published = observed
            events += "published"
        }

        val error = assertThrows(BridgeException::class.java) {
            guard.requireRevalidatedSnapshot(
                snapshot = changed,
                expectedRevision = 2,
                expectedSnapshotId = "observation-2",
            )
        }.also { events += "rejected" }

        assertEquals(listOf("published", "rejected"), events)
        assertSame(changed, published)
        assertEquals("STALE_SNAPSHOT", error.code)
    }

    @Test
    fun sameRevisionIdentityMismatchNeverPublishes() {
        val published = mutableListOf<ConversationSnapshot>()
        val guard = SubmissionSnapshotGuard { published += it }
        val changedIdentity = snapshot(revision = 2, eventId = "unexpected-observation")

        val initialError = assertThrows(BridgeException::class.java) {
            guard.requireInitialSnapshot(
                snapshot = changedIdentity,
                expectedRevision = 2,
                expectedSnapshotId = "expected-observation",
            )
        }
        val revalidationError = assertThrows(BridgeException::class.java) {
            guard.requireRevalidatedSnapshot(
                snapshot = changedIdentity,
                expectedRevision = 2,
                expectedSnapshotId = "expected-observation",
            )
        }

        assertTrue(published.isEmpty())
        assertEquals("STALE_SNAPSHOT_ID", initialError.code)
        assertEquals("STALE_SNAPSHOT", revalidationError.code)
    }

    @Test
    fun freshSnapshotsAreNoOps() {
        val published = mutableListOf<ConversationSnapshot>()
        val guard = SubmissionSnapshotGuard { published += it }
        val fresh = snapshot(revision = 2, eventId = "observation-2")

        guard.requireInitialSnapshot(
            snapshot = fresh,
            expectedRevision = 2,
            expectedSnapshotId = "observation-2",
        )
        guard.requireRevalidatedSnapshot(
            snapshot = fresh,
            expectedRevision = 2,
            expectedSnapshotId = "observation-2",
        )

        assertTrue(published.isEmpty())
    }

    private fun snapshot(revision: Long, eventId: String): ConversationSnapshot =
        ConversationSnapshot(
            targetPackage = ChatSurfacePolicy.EXACT_ROSYTALK_PACKAGE,
            revision = revision,
            capturedAt = "2026-08-14T00:00:00Z",
            items = emptyList(),
            lineage = SnapshotLineage(
                eventId = eventId,
                parentEventId = null,
                sequence = revision,
            ),
        )
}
