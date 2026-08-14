package dev.aster.rosytalkbridge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatSurfacePolicyTest {
    private val liveRosyTalkEvidence = ChatSurfacePolicy.RosyTalkImeEvidence(
        rootPackage = ChatSurfacePolicy.EXACT_ROSYTALK_PACKAGE,
        composerPackage = ChatSurfacePolicy.EXACT_ROSYTALK_PACKAGE,
        composerClassName = ChatSurfacePolicy.NATIVE_EDIT_TEXT_CLASS,
        visibleEnabledEditableCount = 1,
        composerIsPassword = false,
        supportsSetText = true,
        supportsImeEnter = true,
        hasConversationContext = true,
        rootBounds = ChatSurfacePolicy.Bounds(31, 387, 1366, 1973),
        composerBounds = ChatSurfacePolicy.Bounds(275, 1815, 1141, 1973),
    )

    @Test
    fun acceptsExactObservedRosyTalkImeComposer() {
        assertTrue(ChatSurfacePolicy.isExactRosyTalkImeComposer(liveRosyTalkEvidence))
    }

    @Test
    fun rejectsCompatibilityFallbackForAnotherSelectedPackage() {
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(
                    rootPackage = "com.example.other",
                    composerPackage = "com.example.other",
                ),
            ),
        )
    }

    @Test
    fun rejectsGenericOrAmbiguousInputFields() {
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(composerClassName = "android.view.View"),
            ),
        )
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(composerPackage = "com.example.foreign"),
            ),
        )
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(visibleEnabledEditableCount = 2),
            ),
        )
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(composerIsPassword = true),
            ),
        )
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(supportsSetText = false),
            ),
        )
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(supportsImeEnter = false),
            ),
        )
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(hasConversationContext = false),
            ),
        )
    }

    @Test
    fun rejectsImeFieldThatIsNotAWideBottomComposer() {
        assertFalse(
            ChatSurfacePolicy.isExactRosyTalkImeComposer(
                liveRosyTalkEvidence.copy(
                    composerBounds = ChatSurfacePolicy.Bounds(700, 900, 1000, 1050),
                ),
            ),
        )
    }

    @Test
    fun preservesFailureOrderingAndAcceptsNarrowImeCompatibilitySignal() {
        fun stage(
            composerCount: Int = 1,
            adjacentSendCount: Int = 0,
            messageSignal: Boolean = true,
            imeSend: Boolean = true,
            context: Boolean = true,
        ) = ChatSurfacePolicy.failureStage(
            ChatSurfacePolicy.DecisionInput(
                composerCandidateCount = composerCount,
                adjacentSendControlCount = adjacentSendCount,
                composerHasMessageSignal = messageSignal,
                composerHasImeSendAction = imeSend,
                hasConversationContext = context,
            ),
        )

        assertEquals(SurfaceFailureStage.READY, stage())
        assertEquals(SurfaceFailureStage.COMPOSER_MISSING, stage(composerCount = 0))
        assertEquals(SurfaceFailureStage.COMPOSER_AMBIGUOUS, stage(composerCount = 2))
        assertEquals(
            SurfaceFailureStage.SEND_CONTROL_AMBIGUOUS,
            stage(adjacentSendCount = 2),
        )
        assertEquals(
            SurfaceFailureStage.MESSAGE_COMPOSER_SIGNAL_MISSING,
            stage(messageSignal = false),
        )
        assertEquals(
            SurfaceFailureStage.IME_SEND_ACTION_MISSING,
            stage(imeSend = false),
        )
        assertEquals(
            SurfaceFailureStage.CONVERSATION_CONTEXT_MISSING,
            stage(context = false),
        )
        assertEquals(
            SurfaceFailureStage.READY,
            stage(adjacentSendCount = 1, messageSignal = false, imeSend = false),
        )
    }
}
