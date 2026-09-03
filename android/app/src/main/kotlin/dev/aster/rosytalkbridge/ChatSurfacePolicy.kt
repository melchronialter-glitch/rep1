package dev.aster.rosytalkbridge

/**
 * Pure, host-testable policy for the bounded chat-surface recognizer.
 *
 * The exact RosyTalk Android build currently exposes its real message composer as a native
 * EditText with SET_TEXT and IME_ENTER, but without a semantic hint, description, or view ID.
 * Keep that compatibility path package-specific and structurally narrow instead of weakening the
 * generic recognizer for every application the user can select.
 */
internal object ChatSurfacePolicy {
    const val EXACT_ROSYTALK_PACKAGE = "com.rosytalk.ai"
    const val NATIVE_EDIT_TEXT_CLASS = "android.widget.EditText"

    data class Bounds(
        val left: Int,
        val top: Int,
        val right: Int,
        val bottom: Int,
    ) {
        val width: Int get() = right - left
        val height: Int get() = bottom - top
        val centerX: Double get() = (left.toLong() + right.toLong()) / 2.0
        val isValid: Boolean get() = width > 0 && height > 0
    }

    data class RosyTalkImeEvidence(
        val rootPackage: String?,
        val composerPackage: String?,
        val composerClassName: String?,
        val visibleEnabledEditableCount: Int,
        val composerIsPassword: Boolean,
        val supportsSetText: Boolean,
        val supportsImeEnter: Boolean,
        val hasConversationContext: Boolean,
        val rootBounds: Bounds,
        val composerBounds: Bounds,
    )

    data class DecisionInput(
        val composerCandidateCount: Int,
        val adjacentSendControlCount: Int,
        val composerHasMessageSignal: Boolean,
        val composerHasImeSendAction: Boolean,
        val hasConversationContext: Boolean,
    )

    fun isExactRosyTalkImeComposer(evidence: RosyTalkImeEvidence): Boolean {
        if (evidence.rootPackage != EXACT_ROSYTALK_PACKAGE ||
            evidence.composerPackage != EXACT_ROSYTALK_PACKAGE ||
            evidence.composerClassName != NATIVE_EDIT_TEXT_CLASS ||
            evidence.visibleEnabledEditableCount != 1 ||
            evidence.composerIsPassword ||
            !evidence.supportsSetText ||
            !evidence.supportsImeEnter ||
            !evidence.hasConversationContext ||
            !evidence.rootBounds.isValid ||
            !evidence.composerBounds.isValid
        ) {
            return false
        }

        val root = evidence.rootBounds
        val composer = evidence.composerBounds
        val allowedEdgeSlop = maxOf(48, (root.height * 0.04).toInt())
        val bottomGap = root.bottom - composer.bottom
        val normalizedTop = (composer.top - root.top).toDouble() / root.height.toDouble()
        val centerOffset = kotlin.math.abs(composer.centerX - root.centerX)

        return composer.left >= root.left - allowedEdgeSlop &&
            composer.right <= root.right + allowedEdgeSlop &&
            bottomGap in -allowedEdgeSlop..allowedEdgeSlop &&
            normalizedTop >= 0.70 &&
            composer.width >= (root.width * 0.50).toInt() &&
            composer.height <= (root.height * 0.25).toInt() &&
            centerOffset <= root.width * 0.25
    }

    fun failureStage(input: DecisionInput): SurfaceFailureStage = when {
        input.composerCandidateCount == 0 -> SurfaceFailureStage.COMPOSER_MISSING
        input.composerCandidateCount != 1 -> SurfaceFailureStage.COMPOSER_AMBIGUOUS
        input.adjacentSendControlCount > 1 -> SurfaceFailureStage.SEND_CONTROL_AMBIGUOUS
        input.adjacentSendControlCount == 0 && !input.composerHasMessageSignal ->
            SurfaceFailureStage.MESSAGE_COMPOSER_SIGNAL_MISSING
        input.adjacentSendControlCount == 0 && !input.composerHasImeSendAction ->
            SurfaceFailureStage.IME_SEND_ACTION_MISSING
        !input.hasConversationContext -> SurfaceFailureStage.CONVERSATION_CONTEXT_MISSING
        else -> SurfaceFailureStage.READY
    }

}
