package dev.aster.rosytalkbridge

import org.json.JSONArray
import org.json.JSONObject

/**
 * A deliberately metadata-only description of the foreground accessibility surface.
 *
 * This model has no field capable of carrying node text, hint text, content descriptions,
 * window titles, composer drafts, conversation identifiers, or hashes derived from any of
 * those values. Keep the explicit serializer below instead of accepting an arbitrary map.
 */
data class SurfaceDiagnostic(
    val targetConfigured: Boolean,
    val targetForeground: Boolean,
    val rootBounds: ScreenBounds?,
    val windowBounds: ScreenBounds?,
    val observedNodeCount: Int,
    val nodeTraversalTruncated: Boolean,
    val composerCandidateCount: Int,
    val sendControlCandidateCount: Int,
    val composerCandidates: List<SurfaceControlMetadata>,
    val sendControlCandidates: List<SurfaceControlMetadata>,
    val composerCandidatesTruncated: Boolean,
    val sendControlCandidatesTruncated: Boolean,
    val singleComposerCandidate: Boolean,
    val adjacentSendControlCount: Int,
    val composerHasAdjacentSendControl: Boolean,
    val composerHasMessageSignal: Boolean,
    val composerHasImeSendAction: Boolean,
    val conversationContextAboveComposer: Boolean,
    val failureStage: SurfaceFailureStage,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("scope", "foreground_target_metadata_only")
        .put("targetConfigured", targetConfigured)
        .put("targetForeground", targetForeground)
        .put("rootBounds", rootBounds?.toJson() ?: JSONObject.NULL)
        .put("windowBounds", windowBounds?.toJson() ?: JSONObject.NULL)
        .put("observedNodeCount", observedNodeCount)
        .put("nodeTraversalTruncated", nodeTraversalTruncated)
        .put("composerCandidateCount", composerCandidateCount)
        .put("sendControlCandidateCount", sendControlCandidateCount)
        .put("composerCandidates", composerCandidates.toJsonArray())
        .put("sendControlCandidates", sendControlCandidates.toJsonArray())
        .put("composerCandidatesTruncated", composerCandidatesTruncated)
        .put("sendControlCandidatesTruncated", sendControlCandidatesTruncated)
        .put("singleComposerCandidate", singleComposerCandidate)
        .put("adjacentSendControlCount", adjacentSendControlCount)
        .put("composerHasAdjacentSendControl", composerHasAdjacentSendControl)
        .put("composerHasMessageSignal", composerHasMessageSignal)
        .put("composerHasImeSendAction", composerHasImeSendAction)
        .put("conversationContextAboveComposer", conversationContextAboveComposer)
        .put("failureStage", failureStage.wireName)

    private fun List<SurfaceControlMetadata>.toJsonArray(): JSONArray = JSONArray().also { array ->
        forEach { candidate -> array.put(candidate.toJson()) }
    }
}

data class SurfaceControlMetadata(
    val className: String?,
    val viewId: String?,
    val bounds: ScreenBounds,
    val enabled: Boolean,
    val supportedActionIds: List<Int>,
    val supportedActionsTruncated: Boolean,
) {
    fun toJson(): JSONObject {
        val actions = JSONArray()
        supportedActionIds.forEach { actionId -> actions.put(actionId) }
        return JSONObject()
            .put("className", className ?: JSONObject.NULL)
            .put("viewId", viewId ?: JSONObject.NULL)
            .put("bounds", bounds.toJson())
            .put("enabled", enabled)
            .put("supportedActionIds", actions)
            .put("supportedActionsTruncated", supportedActionsTruncated)
    }
}

enum class SurfaceFailureStage(val wireName: String) {
    TARGET_NOT_CONFIGURED("target_not_configured"),
    ACTIVE_ROOT_UNAVAILABLE("active_root_unavailable"),
    TARGET_NOT_FOREGROUND("target_not_foreground"),
    TREE_TRUNCATED("tree_truncated"),
    COMPOSER_MISSING("composer_missing"),
    COMPOSER_AMBIGUOUS("composer_ambiguous"),
    SEND_CONTROL_AMBIGUOUS("send_control_ambiguous"),
    MESSAGE_COMPOSER_SIGNAL_MISSING("message_composer_signal_missing"),
    IME_SEND_ACTION_MISSING("ime_send_action_missing"),
    CONVERSATION_CONTEXT_MISSING("conversation_context_missing"),
    READY("ready"),
}
