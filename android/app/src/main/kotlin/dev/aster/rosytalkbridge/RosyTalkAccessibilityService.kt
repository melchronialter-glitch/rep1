package dev.aster.rosytalkbridge

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

class RosyTalkAccessibilityService : AccessibilityService() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private var revision = 0L
    private var lastSignature: String? = null
    private var observationSequence = 0L
    private var lastObservationId: String? = null
    private var currentObservationParentId: String? = null
    private val publishRunnable = Runnable { publishChangedSnapshot() }

    override fun onServiceConnected() {
        super.onServiceConnected()
        current = this
        refreshPackageFilter()
        BridgeRuntime.initialize(applicationContext)
        BridgeRuntime.accessibilityStateChanged(enabled = true)
    }

    override fun onDestroy() {
        mainHandler.removeCallbacksAndMessages(null)
        if (current === this) current = null
        BridgeRuntime.accessibilityStateChanged(enabled = false)
        super.onDestroy()
    }

    override fun onInterrupt() = Unit

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val selectedPackage = BridgePreferences.targetPackage(this)
        if (selectedPackage.isBlank()) return
        // Defense in depth: serviceInfo.packageNames asks Android to deliver only this package,
        // and this check discards anything else before a window tree is ever requested.
        if (event?.packageName?.toString() != selectedPackage) return

        mainHandler.removeCallbacks(publishRunnable)
        mainHandler.postDelayed(publishRunnable, SNAPSHOT_DEBOUNCE_MS)
    }

    fun refreshPackageFilter() {
        val selectedPackage = BridgePreferences.targetPackage(this)
        val restrictedPackage = selectedPackage.ifBlank { packageName }
        // Failing closed is preferable to ever running with the XML's unrestricted package
        // default. Android supplies serviceInfo after onServiceConnected; require it here.
        val updated = requireNotNull(serviceInfo) { "Accessibility service info is unavailable" }
        updated.packageNames = arrayOf(restrictedPackage)
        serviceInfo = updated
        lastSignature = null
        observationSequence = 0L
        lastObservationId = null
        currentObservationParentId = null
    }

    fun captureSnapshot(maxItems: Int): ConversationSnapshot {
        check(Looper.myLooper() == Looper.getMainLooper()) {
            "Accessibility snapshots must run on the main thread"
        }
        val targetPackage = requireActiveTarget()
        val root = rootInActiveWindow
            ?: throw BridgeException("TARGET_NOT_FOREGROUND", "The selected app has no active window")
        val snapshotNodes = ArrayList<AccessibilityNodeInfo>()
        try {
        if (root.packageName?.toString() != targetPackage) {
            throw BridgeException("TARGET_NOT_FOREGROUND", "Open the selected RosyTalk conversation first")
        }

        if (collectNodes(root, snapshotNodes, 0, isRoot = true)) {
            throw BridgeException(
                "NOT_CHAT_SURFACE",
                "The target accessibility tree is truncated; uniqueness cannot be established",
            )
        }
        identifyChatSurface(root, snapshotNodes)
        val candidates = snapshotNodes
            .asSequence()
            .filter { it.packageName?.toString() == targetPackage }
            .mapNotNull(::visibleTextCandidate)
            .toList()
        val screenWidth = resources.displayMetrics.widthPixels.coerceAtLeast(1)
        val deduplicated = LinkedHashMap<String, TextCandidate>()
        candidates
            .sortedWith(compareBy<TextCandidate> { it.bounds.top }.thenBy { it.bounds.left })
            .forEach { candidate ->
                val key = "${candidate.text}\u0000${candidate.bounds.left},${candidate.bounds.top}," +
                    "${candidate.bounds.right},${candidate.bounds.bottom}"
                deduplicated.putIfAbsent(key, candidate)
            }

        val boundedCandidates = ArrayList<TextCandidate>()
        var totalTextCharacters = 0
        for (candidate in deduplicated.values.take(MAX_VISIBLE_ITEMS)) {
            val remaining = MAX_SNAPSHOT_TEXT_CHARACTERS - totalTextCharacters
            if (remaining <= 0) break
            val boundedCandidate = if (candidate.text.length > remaining) {
                candidate.copy(text = candidate.text.take(remaining))
            } else {
                candidate
            }
            if (boundedCandidate.text.isNotEmpty()) {
                boundedCandidates += boundedCandidate
                totalTextCharacters += boundedCandidate.text.length
            }
        }

        val fullItems = boundedCandidates.mapIndexed { index, candidate ->
            val midpoint = (candidate.bounds.left.toLong() + candidate.bounds.right.toLong()) / 2.0
            val horizontalRatio = midpoint / screenWidth.toDouble()
            val narrowEnoughForGeometry = candidate.bounds.right - candidate.bounds.left < screenWidth * 0.9
            val sender = when {
                narrowEnoughForGeometry && horizontalRatio <= 0.42 -> "remote"
                narrowEnoughForGeometry && horizontalRatio >= 0.58 -> "self"
                else -> "unknown"
            }
            val basis = if (sender == "unknown") "unknown" else "screen_geometry"
            VisibleTextItem(
                localId = stableLocalId(candidate, index),
                text = candidate.text,
                sender = sender,
                senderBasis = basis,
                order = index,
                bounds = ScreenBounds(
                    candidate.bounds.left,
                    candidate.bounds.top,
                    candidate.bounds.right,
                    candidate.bounds.bottom,
                ),
                className = candidate.className,
                viewId = candidate.viewId,
                usedContentDescription = candidate.usedContentDescription,
            )
        }

        // This private signature includes the editable composer, root/window identity, and all
        // visible node state. Composer text is deliberately never placed in the wire snapshot.
        val signature = privateWindowStateSignature(targetPackage, root, snapshotNodes)
        if (lastSignature != signature) {
            lastSignature = signature
            revision = if (revision == Long.MAX_VALUE) 1L else revision + 1L
            observationSequence = if (observationSequence == Long.MAX_VALUE) 1L else observationSequence + 1L
            currentObservationParentId = lastObservationId
            lastObservationId = UUID.randomUUID().toString()
        }

        val observationId = lastObservationId ?: UUID.randomUUID().toString().also {
            lastObservationId = it
            observationSequence = 1L
        }

        return ConversationSnapshot(
            targetPackage = targetPackage,
            revision = revision,
            capturedAt = Instant.now().toString(),
            items = fullItems.take(maxItems.coerceIn(1, MAX_VISIBLE_ITEMS)),
            lineage = SnapshotLineage(
                eventId = observationId,
                parentEventId = currentObservationParentId,
                sequence = observationSequence,
            ),
        )
        } finally {
            recycleCapturedNodes(root, snapshotNodes)
        }
    }

    /**
     * Returns only bounded structural metadata for the selected app's active window. The active
     * root is never traversed unless it belongs to the configured target package, so diagnostics
     * cannot inspect or describe an unrelated foreground app.
     */
    fun captureSurfaceDiagnostic(): SurfaceDiagnostic {
        check(Looper.myLooper() == Looper.getMainLooper()) {
            "Accessibility surface diagnostics must run on the main thread"
        }
        val targetPackage = BridgePreferences.targetPackage(this)
        if (targetPackage.isBlank()) {
            return emptySurfaceDiagnostic(SurfaceFailureStage.TARGET_NOT_CONFIGURED)
        }

        val root = rootInActiveWindow
            ?: return emptySurfaceDiagnostic(SurfaceFailureStage.ACTIVE_ROOT_UNAVAILABLE)
        val diagnosticNodes = ArrayList<AccessibilityNodeInfo>()
        try {
            // Do not collect bounds, metadata, children, or any other property from a non-target
            // window. packageName is read solely for this fail-closed equality check.
            if (root.packageName?.toString() != targetPackage) {
                return emptySurfaceDiagnostic(SurfaceFailureStage.TARGET_NOT_FOREGROUND)
            }

            val traversalTruncated = collectNodes(root, diagnosticNodes, 0, isRoot = true)
            val analysis = analyzeChatSurface(root, diagnosticNodes)
            val reportedStage = if (traversalTruncated) {
                // A truncated tree cannot establish uniqueness, even if the observed subset looks
                // like a chat surface.
                SurfaceFailureStage.TREE_TRUNCATED
            } else {
                analysis.failureStage
            }
            return SurfaceDiagnostic(
                targetConfigured = true,
                targetForeground = true,
                rootBounds = nodeBounds(root).toScreenBounds(),
                windowBounds = targetWindowBounds(root),
                observedNodeCount = diagnosticNodes.size,
                nodeTraversalTruncated = traversalTruncated,
                composerCandidateCount = analysis.composerCandidates.size,
                sendControlCandidateCount = analysis.sendControlCandidates.size,
                composerCandidates = analysis.composerCandidates
                    .take(MAX_DIAGNOSTIC_CANDIDATES)
                    .map(::diagnosticMetadata),
                sendControlCandidates = analysis.sendControlCandidates
                    .take(MAX_DIAGNOSTIC_CANDIDATES)
                    .map(::diagnosticMetadata),
                composerCandidatesTruncated =
                    analysis.composerCandidates.size > MAX_DIAGNOSTIC_CANDIDATES,
                sendControlCandidatesTruncated =
                    analysis.sendControlCandidates.size > MAX_DIAGNOSTIC_CANDIDATES,
                singleComposerCandidate = analysis.composerCandidates.size == 1,
                adjacentSendControlCount = analysis.adjacentSendControls.size,
                composerHasAdjacentSendControl = analysis.adjacentSendControls.isNotEmpty(),
                composerHasMessageSignal = analysis.composerHasMessageSignal,
                composerHasImeSendAction = analysis.composerHasImeSendAction,
                conversationContextAboveComposer = analysis.hasConversationContext,
                failureStage = reportedStage,
            )
        } finally {
            recycleCapturedNodes(root, diagnosticNodes)
        }
    }

    fun submitText(text: String, expectedRevision: Long, expectedSnapshotId: String): SubmitResult {
        check(Looper.myLooper() == Looper.getMainLooper()) {
            "Accessibility submissions must run on the main thread"
        }
        if (!BridgeRuntime.submissionsEnabled) {
            throw BridgeException(
                "SUBMISSIONS_DISABLED",
                "Enable message submission in the Android app for this session",
            )
        }
        if (text.isBlank() || text.length > MAX_MESSAGE_CHARACTERS) {
            throw BridgeException("INVALID_PARAMS", "text must contain 1 to $MAX_MESSAGE_CHARACTERS characters")
        }

        // Bind the action to the exact visible state that Aster most recently read/waited for.
        // This full capture occurs before any field mutation or click.
        val currentSnapshot = captureSnapshot(MAX_VISIBLE_ITEMS)
        if (currentSnapshot.revision != expectedRevision) {
            throw BridgeException(
                "STALE_SNAPSHOT",
                "The visible RosyTalk window changed; read it again before submitting",
            )
        }
        if (currentSnapshot.lineage.eventId != expectedSnapshotId) {
            throw BridgeException(
                "STALE_SNAPSHOT_ID",
                "The visible snapshot ancestry changed; read it again before submitting",
            )
        }
        val targetPackage = currentSnapshot.targetPackage

        // Revalidate after resolving the screen and immediately before any mutation. The second
        // capture catches a draft edit, navigation, or window replacement during preparation.
        val revalidatedSnapshot = captureSnapshot(MAX_VISIBLE_ITEMS)
        if (
            revalidatedSnapshot.revision != expectedRevision ||
            revalidatedSnapshot.lineage.eventId != expectedSnapshotId
        ) {
            throw BridgeException(
                "STALE_SNAPSHOT",
                "The visible RosyTalk window changed; read it again before submitting",
            )
        }
        val actionRoot = rootInActiveWindow
            ?: throw BridgeException("TARGET_NOT_FOREGROUND", "The selected app has no active window")
        val actionNodes = ArrayList<AccessibilityNodeInfo>()
        try {
            if (actionRoot.packageName?.toString() != targetPackage) {
                throw BridgeException("TARGET_NOT_FOREGROUND", "Open the selected RosyTalk conversation first")
            }
            if (collectNodes(actionRoot, actionNodes, 0, isRoot = true)) {
                throw BridgeException(
                    "NOT_CHAT_SURFACE",
                    "The target accessibility tree is truncated; uniqueness cannot be established",
                )
            }
            val surface = identifyChatSurface(actionRoot, actionNodes)
            if (privateWindowStateSignature(targetPackage, actionRoot, actionNodes) != lastSignature) {
                throw BridgeException(
                    "STALE_SNAPSHOT",
                    "The visible RosyTalk window changed immediately before submission",
                )
            }
            val input = surface.composer
            val expectedSurfaceIdentity = surfaceIdentity(actionRoot, actionNodes, surface)
            val originalDraft = input.text?.toString().orEmpty()
            if (originalDraft.isNotBlank()) {
                throw BridgeException(
                    "COMPOSER_NOT_EMPTY",
                    "The visible composer already contains a draft; clear or send it yourself first",
                )
            }

            val setArguments = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
            }
            if (!input.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, setArguments)) {
                restoreDraft(targetPackage, expectedSurfaceIdentity, originalDraft)
                throw BridgeException("SUBMIT_FAILED", "The selected app rejected text entry")
            }

            val method = try {
                val updatedRoot = rootInActiveWindow
                    ?: throw BridgeException(
                        "SUBMIT_FAILED",
                        "The selected app window disappeared after text entry",
                    )
                val updatedNodes = ArrayList<AccessibilityNodeInfo>()
                try {
                    if (updatedRoot.packageName?.toString() != targetPackage) {
                        throw BridgeException(
                            "SUBMIT_FAILED",
                            "The selected app left the foreground after text entry",
                        )
                    }
                    if (collectNodes(updatedRoot, updatedNodes, 0, isRoot = true)) {
                        throw BridgeException(
                            "SUBMIT_FAILED",
                            "The target accessibility tree became truncated after text entry",
                        )
                    }
                    val updatedSurface = identifyChatSurface(updatedRoot, updatedNodes)
                    if (surfaceIdentity(updatedRoot, updatedNodes, updatedSurface) != expectedSurfaceIdentity) {
                        throw BridgeException(
                            "STALE_SURFACE",
                            "The conversation surface changed after text entry; no send action was attempted",
                        )
                    }
                    if (updatedSurface.composer.text?.toString().orEmpty() != text) {
                        throw BridgeException(
                            "SUBMIT_FAILED",
                            "The visible composer does not contain the exact requested text",
                        )
                    }

                    if (surface.sendControl != null) {
                        val updatedSend = updatedSurface.sendControl
                            ?: throw BridgeException(
                                "NO_SUBMIT_CONTROL",
                                "The adjacent send control disappeared after text entry",
                            )
                        if (!updatedSend.isEnabled ||
                            !updatedSend.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                        ) {
                            throw BridgeException(
                                "SUBMIT_FAILED",
                                "The selected app rejected the send-button action",
                            )
                        }
                        "accessibility_click"
                    } else {
                        val imeActionId = updatedSurface.imeActionId
                            ?: throw BridgeException("NO_SUBMIT_CONTROL", "The IME send action disappeared")
                        if (!updatedSurface.composer.performAction(imeActionId)) {
                            throw BridgeException("SUBMIT_FAILED", "The selected app rejected the IME send action")
                        }
                        "ime_enter"
                    }
                } finally {
                    recycleCapturedNodes(updatedRoot, updatedNodes)
                }
            } catch (error: BridgeException) {
                restoreDraft(targetPackage, expectedSurfaceIdentity, originalDraft)
                throw error
            } catch (_: Exception) {
                restoreDraft(targetPackage, expectedSurfaceIdentity, originalDraft)
                throw BridgeException(
                    "SUBMIT_FAILED",
                    "Message submission failed; restoring the prior draft was attempted",
                )
            }

            mainHandler.removeCallbacks(publishRunnable)
            mainHandler.postDelayed(publishRunnable, SNAPSHOT_AFTER_SUBMIT_MS)
            return SubmitResult(
                targetPackage = targetPackage,
                method = method,
                basedOnRevision = expectedRevision,
                basedOnEventId = expectedSnapshotId,
                eventId = UUID.randomUUID().toString(),
            )
        } finally {
            recycleCapturedNodes(actionRoot, actionNodes)
        }
    }

    private fun publishChangedSnapshot() {
        val previousRevision = revision
        try {
            val snapshot = captureSnapshot(MAX_VISIBLE_ITEMS)
            if (snapshot.revision != previousRevision) BridgeRuntime.publishSnapshot(snapshot)
        } catch (_: BridgeException) {
            // A target window can disappear during the debounce interval. No unrelated window
            // is inspected and no stale snapshot is published.
        }
    }

    private fun requireActiveTarget(): String {
        val targetPackage = BridgePreferences.targetPackage(this)
        if (targetPackage.isBlank()) {
            throw BridgeException("TARGET_NOT_CONFIGURED", "Select the RosyTalk app in the bridge first")
        }
        return targetPackage
    }

    private fun visibleTextCandidate(node: AccessibilityNodeInfo): TextCandidate? {
        if (node.isEditable || !node.isVisibleToUser) return null
        val nodeText = node.text?.toString()?.trim().orEmpty()
        val description = node.contentDescription?.toString()?.trim().orEmpty()
        val text = nodeText.ifBlank { description }
        if (text.isBlank() || text.length > MAX_MESSAGE_CHARACTERS) return null
        val bounds = nodeBounds(node)
        if (bounds.isEmpty()) return null
        return TextCandidate(
            text = text,
            bounds = bounds,
            className = node.className?.toString()?.take(MAX_METADATA_CHARACTERS),
            viewId = node.viewIdResourceName?.take(MAX_METADATA_CHARACTERS),
            usedContentDescription = nodeText.isBlank(),
        )
    }

    private fun collectNodes(
        node: AccessibilityNodeInfo,
        output: MutableList<AccessibilityNodeInfo>,
        depth: Int,
        isRoot: Boolean = false,
    ): Boolean {
        if (depth > MAX_TREE_DEPTH || output.size >= MAX_TREE_NODES || !node.isVisibleToUser) {
            if (!isRoot) recycleNode(node)
            return depth > MAX_TREE_DEPTH || output.size >= MAX_TREE_NODES
        }
        output += node
        val rawChildCount = node.childCount
        val childCount = rawChildCount.coerceAtMost(MAX_CHILDREN_PER_NODE)
        var truncated = rawChildCount > childCount
        for (index in 0 until childCount) {
            val child = node.getChild(index)
            if (child == null) {
                // Android may expose a child count whose node has already gone stale. Unseen
                // descendants could contain another composer or action, so uniqueness is unknown.
                truncated = true
            } else {
                if (collectNodes(child, output, depth + 1)) truncated = true
            }
            if (output.size >= MAX_TREE_NODES) {
                if (index + 1 < childCount) truncated = true
                break
            }
        }
        return truncated
    }

    private fun recycleCapturedNodes(
        root: AccessibilityNodeInfo,
        nodes: List<AccessibilityNodeInfo>,
    ) {
        if (Build.VERSION.SDK_INT >= 33) return
        val rootWasCollected = nodes.any { it === root }
        nodes.forEach(::recycleNode)
        if (!rootWasCollected) recycleNode(root)
    }

    @Suppress("DEPRECATION")
    private fun recycleNode(node: AccessibilityNodeInfo) {
        if (Build.VERSION.SDK_INT < 33) node.recycle()
    }

    private fun looksLikeSendControl(node: AccessibilityNodeInfo): Boolean {
        val text = node.text?.toString().orEmpty().trim().lowercase()
        val description = node.contentDescription?.toString().orEmpty().trim().lowercase()
        val viewId = node.viewIdResourceName.orEmpty().lowercase()
        val exactLabels = setOf("send", "send message")
        val idTail = viewId.substringAfterLast('/').replace('-', '_')
        val idSignalsSend = idTail in setOf(
            "send",
            "send_button",
            "button_send",
            "btn_send",
            "send_message",
            "message_send",
        )
        return node.isClickable && (text in exactLabels || description in exactLabels || idSignalsSend)
    }

    private fun identifyChatSurface(
        root: AccessibilityNodeInfo,
        nodes: List<AccessibilityNodeInfo>,
    ): ChatSurface {
        val analysis = analyzeChatSurface(root, nodes)
        when (analysis.failureStage) {
            SurfaceFailureStage.COMPOSER_MISSING -> throw BridgeException(
                "NOT_CHAT_SURFACE",
                "The target window does not expose a bottom message composer",
            )
            SurfaceFailureStage.COMPOSER_AMBIGUOUS -> throw BridgeException(
                "NOT_CHAT_SURFACE",
                "The target window exposes multiple bottom message composers",
            )
            SurfaceFailureStage.SEND_CONTROL_AMBIGUOUS -> throw BridgeException(
                "NOT_CHAT_SURFACE",
                "The target window exposes multiple adjacent send controls",
            )
            SurfaceFailureStage.MESSAGE_COMPOSER_SIGNAL_MISSING -> throw BridgeException(
                "NOT_CHAT_SURFACE",
                "The composer lacks an explicit message-composer signal",
            )
            SurfaceFailureStage.IME_SEND_ACTION_MISSING -> throw BridgeException(
                "NOT_CHAT_SURFACE",
                "The composer lacks an adjacent Send control or an exposed IME send action",
            )
            SurfaceFailureStage.CONVERSATION_CONTEXT_MISSING -> throw BridgeException(
                "NOT_CHAT_SURFACE",
                "No visible conversation context appears above the message composer",
            )
            SurfaceFailureStage.READY -> Unit
            else -> throw BridgeException(
                "NOT_CHAT_SURFACE",
                "The target window could not be identified as a safe chat surface",
            )
        }
        val composer = requireNotNull(analysis.composerCandidates.singleOrNull())
        return ChatSurface(
            composer = composer,
            sendControl = analysis.adjacentSendControls.singleOrNull(),
            imeActionId = if (analysis.adjacentSendControls.isEmpty()) analysis.imeActionId else null,
        )
    }

    private fun analyzeChatSurface(
        root: AccessibilityNodeInfo,
        nodes: List<AccessibilityNodeInfo>,
    ): ChatSurfaceAnalysis {
        val rootBounds = nodeBounds(root)
        val rootPackage = root.packageName?.toString()
        val effectiveHeight = rootBounds.height().takeIf { it > 0 } ?: resources.displayMetrics.heightPixels
        val effectiveWidth = rootBounds.width().takeIf { it > 0 } ?: resources.displayMetrics.widthPixels
        val bottomThreshold = rootBounds.top + (effectiveHeight * 0.55).toInt()
        val visibleEnabledEditables = nodes.filter { node ->
            if (!node.isVisibleToUser || !node.isEnabled || !node.isEditable) return@filter false
            !nodeBounds(node).isEmpty()
        }
        val composers = visibleEnabledEditables.filter { node ->
            if (node.packageName?.toString() != rootPackage) return@filter false
            val bounds = nodeBounds(node)
            bounds.centerY() >= bottomThreshold &&
                bounds.width() >= (effectiveWidth * MIN_COMPOSER_WIDTH_RATIO).toInt()
        }
        val sendControlCandidates = nodes.filter { node ->
            node.packageName?.toString() == rootPackage &&
                node.isVisibleToUser && looksLikeSendControl(node)
        }
        if (composers.size != 1) {
            return ChatSurfaceAnalysis(
                composerCandidates = composers,
                sendControlCandidates = sendControlCandidates,
                adjacentSendControls = emptyList(),
                composerHasMessageSignal = false,
                composerHasImeSendAction = false,
                hasConversationContext = false,
                imeActionId = null,
                failureStage = if (composers.isEmpty()) {
                    SurfaceFailureStage.COMPOSER_MISSING
                } else {
                    SurfaceFailureStage.COMPOSER_AMBIGUOUS
                },
            )
        }
        val composer = composers.single()
        val composerBounds = nodeBounds(composer)

        val adjacentSendControls = sendControlCandidates.filter { node ->
            node !== composer &&
                isSpatiallyAdjacent(composerBounds, nodeBounds(node), effectiveWidth)
        }

        val composerSignals = listOf(
            composer.hintText?.toString(),
            composer.contentDescription?.toString(),
            composer.viewIdResourceName,
        ).joinToString(" ").lowercase()
        val composerIsMessageLike =
            listOf("message", "chat", "composer", "reply").any(composerSignals::contains)
        val imeActionId = if (Build.VERSION.SDK_INT >= 30) {
            AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id
        } else {
            null
        }
        val exposedImeSend = imeActionId?.takeIf { id -> composer.actionList.any { it.id == id } }

        val hasConversationContext = nodes.any { node ->
            if (node === composer || node.isEditable || looksLikeSendControl(node)) return@any false
            if (node.packageName?.toString() != rootPackage) return@any false
            val text = node.text?.toString()?.trim().orEmpty()
                .ifBlank { node.contentDescription?.toString()?.trim().orEmpty() }
            val bounds = nodeBounds(node)
            text.isNotBlank() && bounds.bottom <= composerBounds.top
        }
        val supportsSetText = composer.actionList.any {
            it.id == AccessibilityNodeInfo.ACTION_SET_TEXT
        }
        val exactRosyTalkImeComposer = ChatSurfacePolicy.isExactRosyTalkImeComposer(
            ChatSurfacePolicy.RosyTalkImeEvidence(
                rootPackage = rootPackage,
                composerPackage = composer.packageName?.toString(),
                composerClassName = composer.className?.toString(),
                visibleEnabledEditableCount = visibleEnabledEditables.size,
                composerIsPassword = composer.isPassword,
                supportsSetText = supportsSetText,
                supportsImeEnter = exposedImeSend != null,
                hasConversationContext = hasConversationContext,
                rootBounds = rootBounds.toPolicyBounds(),
                composerBounds = composerBounds.toPolicyBounds(),
            ),
        )
        val composerSignalAccepted = composerIsMessageLike || exactRosyTalkImeComposer
        val failureStage = ChatSurfacePolicy.failureStage(
            ChatSurfacePolicy.DecisionInput(
                composerCandidateCount = composers.size,
                adjacentSendControlCount = adjacentSendControls.size,
                composerHasMessageSignal = composerSignalAccepted,
                composerHasImeSendAction = exposedImeSend != null,
                hasConversationContext = hasConversationContext,
            ),
        )

        return ChatSurfaceAnalysis(
            composerCandidates = composers,
            sendControlCandidates = sendControlCandidates,
            adjacentSendControls = adjacentSendControls,
            // Preserve the raw lexical observation in diagnostics. The package-specific
            // compatibility result affects acceptance, not what RosyTalk actually exposed.
            composerHasMessageSignal = composerIsMessageLike,
            composerHasImeSendAction = exposedImeSend != null,
            hasConversationContext = hasConversationContext,
            imeActionId = if (adjacentSendControls.isEmpty()) exposedImeSend else null,
            failureStage = failureStage,
        )
    }

    private fun isSpatiallyAdjacent(
        composer: Rect,
        control: Rect,
        windowWidth: Int,
    ): Boolean {
        if (control.isEmpty()) return false
        val verticalAllowance = composer.height().coerceAtLeast(MIN_CONTROL_ALLOWANCE_PX)
        if (control.centerY() < composer.top - verticalAllowance ||
            control.centerY() > composer.bottom + verticalAllowance
        ) {
            return false
        }
        val horizontalGap = when {
            control.right < composer.left -> composer.left - control.right
            control.left > composer.right -> control.left - composer.right
            else -> 0
        }
        return horizontalGap <= (windowWidth * MAX_SEND_GAP_RATIO).toInt()
    }

    private fun Rect.toPolicyBounds(): ChatSurfacePolicy.Bounds = ChatSurfacePolicy.Bounds(
        left = left,
        top = top,
        right = right,
        bottom = bottom,
    )

    private fun privateWindowStateSignature(
        targetPackage: String,
        root: AccessibilityNodeInfo,
        nodes: List<AccessibilityNodeInfo>,
    ): String {
        val digest = MessageDigest.getInstance("SHA-256")
        fun add(value: String?) {
            digest.update(value.orEmpty().toByteArray(StandardCharsets.UTF_8))
            digest.update(0.toByte())
        }
        add(targetPackage)
        add(root.windowId.toString())
        add(root.window?.title?.toString())
        nodes.forEach { node ->
            val bounds = nodeBounds(node)
            add(node.packageName?.toString())
            add(node.windowId.toString())
            add(node.className?.toString())
            add(node.viewIdResourceName)
            add(node.text?.toString()?.take(MAX_MESSAGE_CHARACTERS))
            add(node.hintText?.toString()?.take(MAX_MESSAGE_CHARACTERS))
            add(node.contentDescription?.toString()?.take(MAX_MESSAGE_CHARACTERS))
            add(bounds.flattenToString())
            add(if (node.isEditable) "editable" else "fixed")
            add(if (node.isEnabled) "enabled" else "disabled")
            add(if (node.isClickable) "clickable" else "not_clickable")
        }
        return Base64.encodeToString(
            digest.digest(),
            Base64.NO_WRAP or Base64.NO_PADDING or Base64.URL_SAFE,
        )
    }

    private fun surfaceIdentity(
        root: AccessibilityNodeInfo,
        nodes: List<AccessibilityNodeInfo>,
        surface: ChatSurface,
    ): SurfaceIdentity {
        fun bounds(node: AccessibilityNodeInfo): ScreenBounds {
            val rect = nodeBounds(node)
            return ScreenBounds(rect.left, rect.top, rect.right, rect.bottom)
        }
        fun control(node: AccessibilityNodeInfo): ControlIdentity = ControlIdentity(
            className = node.className?.toString(),
            viewId = node.viewIdResourceName,
            bounds = bounds(node),
            hint = node.hintText?.toString(),
            description = node.contentDescription?.toString(),
            label = node.text?.toString(),
        )

        return SurfaceIdentity(
            windowId = root.windowId,
            windowTitle = root.window?.title?.toString(),
            rootClassName = root.className?.toString(),
            rootViewId = root.viewIdResourceName,
            rootBounds = bounds(root),
            composer = control(surface.composer).copy(label = null),
            sendControl = surface.sendControl?.let(::control),
            usesIme = surface.sendControl == null && surface.imeActionId != null,
            contextSignature = conversationContextSignature(nodes, surface),
        )
    }

    private fun conversationContextSignature(
        nodes: List<AccessibilityNodeInfo>,
        surface: ChatSurface,
    ): String {
        val composerTop = nodeBounds(surface.composer).top
        val digest = MessageDigest.getInstance("SHA-256")
        fun add(value: String?) {
            digest.update(value.orEmpty().toByteArray(StandardCharsets.UTF_8))
            digest.update(0.toByte())
        }
        nodes.forEach { node ->
            if (node === surface.composer || node === surface.sendControl || node.isEditable) {
                return@forEach
            }
            val bounds = nodeBounds(node)
            // Context above the composer carries the visible conversation/header identity while
            // excluding the composer row whose enabled/label state may change after text entry.
            if (bounds.isEmpty() || bounds.bottom > composerTop) return@forEach
            add(node.packageName?.toString())
            add(node.windowId.toString())
            add(node.className?.toString())
            add(node.viewIdResourceName)
            add(node.text?.toString()?.take(MAX_MESSAGE_CHARACTERS))
            add(node.hintText?.toString()?.take(MAX_MESSAGE_CHARACTERS))
            add(node.contentDescription?.toString()?.take(MAX_MESSAGE_CHARACTERS))
            add(bounds.flattenToString())
        }
        return Base64.encodeToString(
            digest.digest(),
            Base64.NO_WRAP or Base64.NO_PADDING or Base64.URL_SAFE,
        )
    }

    private fun restoreDraft(
        targetPackage: String,
        expectedSurfaceIdentity: SurfaceIdentity,
        originalDraft: String,
    ): Boolean {
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, originalDraft)
        }
        val root = rootInActiveWindow ?: return false
        val nodes = ArrayList<AccessibilityNodeInfo>()
        try {
            if (root.packageName?.toString() != targetPackage) return false
            if (collectNodes(root, nodes, 0, isRoot = true)) return false
            val currentSurface = try {
                identifyChatSurface(root, nodes)
            } catch (_: BridgeException) {
                return false
            }
            if (surfaceIdentity(root, nodes, currentSurface) != expectedSurfaceIdentity) return false
            return currentSurface.composer.performAction(
                AccessibilityNodeInfo.ACTION_SET_TEXT,
                arguments,
            )
        } finally {
            recycleCapturedNodes(root, nodes)
        }
    }

    private fun nodeBounds(node: AccessibilityNodeInfo): Rect =
        Rect().also { node.getBoundsInScreen(it) }

    private fun Rect.toScreenBounds(): ScreenBounds = ScreenBounds(left, top, right, bottom)

    private fun targetWindowBounds(root: AccessibilityNodeInfo): ScreenBounds? {
        val window = root.window ?: return null
        return try {
            Rect().also(window::getBoundsInScreen).toScreenBounds()
        } finally {
            recycleWindow(window)
        }
    }

    @Suppress("DEPRECATION")
    private fun recycleWindow(window: AccessibilityWindowInfo) {
        if (Build.VERSION.SDK_INT < 33) window.recycle()
    }

    private fun diagnosticMetadata(node: AccessibilityNodeInfo): SurfaceControlMetadata {
        val actionIds = node.actionList.map { action -> action.id }.distinct().sorted()
        return SurfaceControlMetadata(
            className = node.className?.toString()?.take(MAX_DIAGNOSTIC_METADATA_CHARACTERS),
            viewId = node.viewIdResourceName?.take(MAX_DIAGNOSTIC_METADATA_CHARACTERS),
            bounds = nodeBounds(node).toScreenBounds(),
            enabled = node.isEnabled,
            supportedActionIds = actionIds.take(MAX_DIAGNOSTIC_ACTIONS),
            supportedActionsTruncated = actionIds.size > MAX_DIAGNOSTIC_ACTIONS,
        )
    }

    private fun emptySurfaceDiagnostic(failureStage: SurfaceFailureStage): SurfaceDiagnostic =
        SurfaceDiagnostic(
            targetConfigured = failureStage != SurfaceFailureStage.TARGET_NOT_CONFIGURED,
            targetForeground = false,
            rootBounds = null,
            windowBounds = null,
            observedNodeCount = 0,
            nodeTraversalTruncated = false,
            composerCandidateCount = 0,
            sendControlCandidateCount = 0,
            composerCandidates = emptyList(),
            sendControlCandidates = emptyList(),
            composerCandidatesTruncated = false,
            sendControlCandidatesTruncated = false,
            singleComposerCandidate = false,
            adjacentSendControlCount = 0,
            composerHasAdjacentSendControl = false,
            composerHasMessageSignal = false,
            composerHasImeSendAction = false,
            conversationContextAboveComposer = false,
            failureStage = failureStage,
        )

    private fun stableLocalId(candidate: TextCandidate, order: Int): String {
        val source = "$order\u0000${candidate.text}\u0000${candidate.bounds.flattenToString()}"
        return UUID.nameUUIDFromBytes(source.toByteArray(StandardCharsets.UTF_8)).toString()
    }

    private data class TextCandidate(
        val text: String,
        val bounds: Rect,
        val className: String?,
        val viewId: String?,
        val usedContentDescription: Boolean,
    )

    private data class ChatSurface(
        val composer: AccessibilityNodeInfo,
        val sendControl: AccessibilityNodeInfo?,
        val imeActionId: Int?,
    )

    private data class ChatSurfaceAnalysis(
        val composerCandidates: List<AccessibilityNodeInfo>,
        val sendControlCandidates: List<AccessibilityNodeInfo>,
        val adjacentSendControls: List<AccessibilityNodeInfo>,
        val composerHasMessageSignal: Boolean,
        val composerHasImeSendAction: Boolean,
        val hasConversationContext: Boolean,
        val imeActionId: Int?,
        val failureStage: SurfaceFailureStage,
    )

    private data class ControlIdentity(
        val className: String?,
        val viewId: String?,
        val bounds: ScreenBounds,
        val hint: String?,
        val description: String?,
        val label: String?,
    )

    private data class SurfaceIdentity(
        val windowId: Int,
        val windowTitle: String?,
        val rootClassName: String?,
        val rootViewId: String?,
        val rootBounds: ScreenBounds,
        val composer: ControlIdentity,
        val sendControl: ControlIdentity?,
        val usesIme: Boolean,
        val contextSignature: String,
    )

    companion object {
        @Volatile
        var current: RosyTalkAccessibilityService? = null
            private set

        const val MAX_VISIBLE_ITEMS = 200
        const val MAX_MESSAGE_CHARACTERS = 16_000
        private const val MAX_SNAPSHOT_TEXT_CHARACTERS = 256 * 1024
        const val MAX_SAFE_REVISION = 9_007_199_254_740_991L
        private const val MAX_METADATA_CHARACTERS = 500
        private const val MAX_TREE_NODES = 2_000
        private const val MAX_TREE_DEPTH = 50
        private const val MAX_CHILDREN_PER_NODE = 200
        private const val MAX_DIAGNOSTIC_CANDIDATES = 12
        private const val MAX_DIAGNOSTIC_ACTIONS = 32
        private const val MAX_DIAGNOSTIC_METADATA_CHARACTERS = 160
        private const val MIN_CONTROL_ALLOWANCE_PX = 48
        private const val MIN_COMPOSER_WIDTH_RATIO = 0.15
        private const val MAX_SEND_GAP_RATIO = 0.25
        private const val SNAPSHOT_DEBOUNCE_MS = 300L
        private const val SNAPSHOT_AFTER_SUBMIT_MS = 450L
    }
}
