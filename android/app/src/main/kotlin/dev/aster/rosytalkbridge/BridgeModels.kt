package dev.aster.rosytalkbridge

import org.json.JSONArray
import org.json.JSONObject

class BridgeException(
    val code: String,
    override val message: String,
) : Exception(message)

data class ScreenBounds(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("left", left)
        .put("top", top)
        .put("right", right)
        .put("bottom", bottom)
}

data class VisibleTextItem(
    val localId: String,
    val text: String,
    val sender: String,
    val senderBasis: String,
    val order: Int,
    val bounds: ScreenBounds,
    val className: String?,
    val viewId: String?,
    val usedContentDescription: Boolean,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("localId", localId)
        .put("text", text)
        .put("sender", sender)
        .put("senderBasis", senderBasis)
        .put("order", order)
        .put("bounds", bounds.toJson())
        .put("className", className ?: JSONObject.NULL)
        .put("viewId", viewId ?: JSONObject.NULL)
        .put("usedContentDescription", usedContentDescription)
}

data class ConversationSnapshot(
    val targetPackage: String,
    val revision: Long,
    val capturedAt: String,
    val items: List<VisibleTextItem>,
    val lineage: SnapshotLineage,
) {
    fun toJson(): JSONObject {
        val encodedItems = JSONArray()
        items.forEach { encodedItems.put(it.toJson()) }
        return JSONObject()
            .put("targetPackage", targetPackage)
            .put("revision", revision)
            .put("capturedAt", capturedAt)
            .put("windowTitle", JSONObject.NULL)
            .put("scope", "visible_target_window")
            // Accessibility exposes only the currently materialized window tree. This must
            // never be represented as a complete conversation transcript.
            .put("complete", false)
            .put("items", encodedItems)
            .put("lineage", lineage.toJson())
    }
}

data class SnapshotLineage(
    val eventId: String,
    val parentEventId: String?,
    val sequence: Long,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("eventId", eventId)
        .put("parentEventId", parentEventId ?: JSONObject.NULL)
        .put("sequence", sequence)
        .put("source", "android_accessibility_window")
        .put("evidenceClass", "foreground_accessibility_observation")
}

data class SubmitResult(
    val targetPackage: String,
    val method: String,
    val basedOnRevision: Long,
    val basedOnEventId: String,
    val eventId: String,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("submitted", true)
        // A successful accessibility action means only that the local UI accepted it. It is
        // not evidence that RosyTalk or the remote participant delivered/received the text.
        .put("deliveryConfirmed", false)
        .put("method", method)
        .put("targetPackage", targetPackage)
        .put("actedAt", java.time.Instant.now().toString())
        .put("basedOnRevision", basedOnRevision)
        .put(
            "lineage",
            JSONObject()
                .put("eventId", eventId)
                .put("basedOnEventId", basedOnEventId)
                .put("source", "android_accessibility_action")
                .put("evidenceClass", "local_ui_action_result"),
        )
}
