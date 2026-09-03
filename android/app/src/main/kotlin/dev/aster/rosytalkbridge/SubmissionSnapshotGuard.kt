package dev.aster.rosytalkbridge

/**
 * Keeps a rejected submission's newly observed snapshot in the public lineage.
 *
 * [RosyTalkAccessibilityService.captureSnapshot] advances its revision and ancestry whenever the
 * visible window changes. A submission revalidation capture is normally private, but if that
 * capture discovers a new revision it must be published before the stale error is returned.
 * Otherwise the next public snapshot would descend from an observation the relay never received.
 */
internal class SubmissionSnapshotGuard(
    private val publishObservedSnapshot: (ConversationSnapshot) -> Unit,
) {
    fun requireInitialSnapshot(
        snapshot: ConversationSnapshot,
        expectedRevision: Long,
        expectedSnapshotId: String,
    ) {
        requireFresh(
            snapshot = snapshot,
            expectedRevision = expectedRevision,
            expectedSnapshotId = expectedSnapshotId,
            eventIdMismatchCode = "STALE_SNAPSHOT_ID",
            eventIdMismatchMessage =
                "The visible snapshot ancestry changed; read it again before submitting",
        )
    }

    fun requireRevalidatedSnapshot(
        snapshot: ConversationSnapshot,
        expectedRevision: Long,
        expectedSnapshotId: String,
    ) {
        requireFresh(
            snapshot = snapshot,
            expectedRevision = expectedRevision,
            expectedSnapshotId = expectedSnapshotId,
            eventIdMismatchCode = "STALE_SNAPSHOT",
            eventIdMismatchMessage =
                "The visible RosyTalk window changed; read it again before submitting",
        )
    }

    private fun requireFresh(
        snapshot: ConversationSnapshot,
        expectedRevision: Long,
        expectedSnapshotId: String,
        eventIdMismatchCode: String,
        eventIdMismatchMessage: String,
    ) {
        if (snapshot.revision != expectedRevision) {
            // Publish synchronously before throwing. WebSocket frames are enqueued in call order,
            // so the relay observes this lineage node before the stale submission response.
            publishObservedSnapshot(snapshot)
            throw BridgeException(
                "STALE_SNAPSHOT",
                "The visible RosyTalk window changed; read it again before submitting",
            )
        }
        if (snapshot.lineage.eventId != expectedSnapshotId) {
            // Do not publish a same-revision/different-ID observation: the relay correctly treats
            // that shape as invalid lineage. Reconnection is the safe recovery for that case.
            throw BridgeException(eventIdMismatchCode, eventIdMismatchMessage)
        }
    }
}
