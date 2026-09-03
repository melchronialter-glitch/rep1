package dev.aster.rosytalkbridge

import org.json.JSONObject
import java.time.Instant
import java.util.UUID

enum class AsterExpression(
    val wireName: String,
    val displayName: String,
) {
    NEUTRAL("neutral", "Neutral"),
    THINKING("thinking", "Thinking"),
    AMUSED("amused", "Amused"),
    SOFT("soft", "Soft"),
    FIERCE("fierce", "Fierce"),
    FLUSTERED("flustered", "Flustered"),
    BLUSH("blush", "Blush");

    override fun toString(): String = displayName

    companion object {
        fun fromWireName(value: String): AsterExpression? =
            entries.firstOrNull { it.wireName == value }
    }
}

enum class ExpressionAuthor(val displayName: String) {
    DEFAULT("default"),
    USER("you"),
    MCP("authenticated MCP"),
}

data class AsterRoomExpressionState(
    val expression: AsterExpression,
    val caption: String?,
    val author: ExpressionAuthor,
    val authoredAt: String,
    val appliedAt: String,
    val authoredEventId: String,
    val appliedEventId: String,
)

data class RoomExpressionApplyResult(
    val state: AsterRoomExpressionState,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("applied", true)
        .put("state", state.expression.wireName)
        .put("caption", state.caption ?: JSONObject.NULL)
        .put("appliedAt", state.appliedAt)
        .put(
            "lineage",
            JSONObject()
                .put("eventId", state.appliedEventId)
                .put("basedOnEventId", state.authoredEventId)
                .put("source", "android_room_ui")
                .put("evidenceClass", "local_ui_state_result"),
        )
}

fun defaultAsterRoomExpressionState(): AsterRoomExpressionState {
    val now = Instant.now().toString()
    return AsterRoomExpressionState(
        expression = AsterExpression.NEUTRAL,
        caption = null,
        author = ExpressionAuthor.DEFAULT,
        authoredAt = now,
        appliedAt = now,
        authoredEventId = UUID.randomUUID().toString(),
        appliedEventId = UUID.randomUUID().toString(),
    )
}
