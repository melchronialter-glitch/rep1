package dev.aster.rosytalkbridge

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.time.Instant
import java.util.UUID

enum class ConnectionState {
    DISCONNECTED,
    CONNECTING,
    READY,
}

interface BridgeListener {
    fun onConnectionState(state: ConnectionState, detail: String)
    fun onActivity(message: String)
    fun onSnapshot(snapshot: ConversationSnapshot) = Unit
    fun onSnapshotCleared() = Unit
    fun onRoomExpression(state: AsterRoomExpressionState) = Unit
}

/** Process-local runtime. The WebSocket stays outbound-only and can live with the enabled
 * accessibility service after the setup Activity leaves the foreground. */
object BridgeRuntime : BridgeListener {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val submissionExpiryRunnable = object : Runnable {
        override fun run() {
            val remaining = submissionExpiresAtElapsedMs - SystemClock.elapsedRealtime()
            if (submissionExpiresAtElapsedMs == 0L) {
                return
            } else if (remaining > 0L) {
                mainHandler.postDelayed(this, remaining)
            } else {
                submissionExpiresAtElapsedMs = 0L
                onActivity("Aster message-submission and expression authorization expired")
                if (initialized && client.isActive) client.refreshCapabilities()
            }
        }
    }

    @Volatile
    private var uiListener: BridgeListener? = null

    @Volatile
    private var initialized = false

    @Volatile
    private var submissionExpiresAtElapsedMs = 0L

    @Volatile
    private var mirroredSnapshot: ConversationSnapshot? = null

    @Volatile
    private var expressionState: AsterRoomExpressionState = defaultAsterRoomExpressionState()

    val submissionsEnabled: Boolean
        get() = submissionExpiresAtElapsedMs > SystemClock.elapsedRealtime()

    private lateinit var client: BridgeClient

    fun initialize(context: Context) {
        if (initialized) return
        synchronized(this) {
            if (initialized) return
            client = BridgeClient(context.applicationContext, this)
            initialized = true
        }
    }

    fun attach(listener: BridgeListener) {
        uiListener = listener
        if (initialized) {
            listener.onConnectionState(client.state, client.stateDetail)
        }
        mirroredSnapshot?.let(listener::onSnapshot)
        listener.onRoomExpression(expressionState)
    }

    fun detach(listener: BridgeListener) {
        if (uiListener === listener) uiListener = null
    }

    fun connect(url: String, token: String) {
        check(initialized) { "Bridge runtime is not initialized" }
        client.connect(url, token)
    }

    fun disconnect(detail: String = "Disconnected") {
        disableSubmissions("Aster actions disabled on disconnect")
        if (initialized) client.disconnect(detail)
    }

    fun setSubmissionsEnabled(enabled: Boolean) {
        mainHandler.removeCallbacks(submissionExpiryRunnable)
        submissionExpiresAtElapsedMs = if (enabled) {
            SystemClock.elapsedRealtime() + SUBMISSION_AUTHORIZATION_MS
        } else {
            0L
        }
        if (enabled) {
            mainHandler.postDelayed(submissionExpiryRunnable, SUBMISSION_AUTHORIZATION_MS)
        }
        onActivity(
            if (enabled) {
                "Aster message submission and remote expression changes enabled for 15 minutes"
            } else {
                "Aster message submission and remote expression changes disabled"
            },
        )
        if (initialized && client.isActive) client.refreshCapabilities()
    }

    fun targetConfigurationChanged() {
        disableSubmissions("Aster actions disabled because the target changed")
        mirroredSnapshot = null
        uiListener?.onSnapshotCleared()
        RosyTalkAccessibilityService.current?.refreshPackageFilter()
        if (initialized && client.isActive) client.refreshCapabilities()
    }

    fun accessibilityStateChanged(enabled: Boolean) {
        if (!enabled) {
            disableSubmissions("Aster actions disabled because Accessibility stopped")
            mirroredSnapshot = null
            uiListener?.onSnapshotCleared()
        }
        if (initialized && client.isActive) client.refreshCapabilities()
    }

    fun publishSnapshot(snapshot: ConversationSnapshot) {
        mirrorSnapshot(snapshot)
        if (initialized) client.publishSnapshot(snapshot)
    }

    fun mirrorSnapshot(snapshot: ConversationSnapshot) {
        mirroredSnapshot = snapshot
        uiListener?.onSnapshot(snapshot)
    }

    val latestSnapshot: ConversationSnapshot?
        get() = mirroredSnapshot

    val currentRoomExpression: AsterRoomExpressionState
        get() = expressionState

    fun setLocalRoomExpression(expression: AsterExpression): AsterRoomExpressionState {
        val now = Instant.now().toString()
        val next = AsterRoomExpressionState(
            expression = expression,
            caption = null,
            author = ExpressionAuthor.USER,
            authoredAt = now,
            appliedAt = now,
            authoredEventId = UUID.randomUUID().toString(),
            appliedEventId = UUID.randomUUID().toString(),
        )
        expressionState = next
        uiListener?.onRoomExpression(next)
        onActivity("Aster expression set to ${expression.wireName} by the phone user")
        return next
    }

    fun applyRemoteRoomExpression(
        expression: AsterExpression,
        caption: String?,
        authoredAt: String,
        authoredEventId: String,
    ): RoomExpressionApplyResult {
        if (!submissionsEnabled) {
            throw BridgeException(
                "SUBMISSIONS_DISABLED",
                "Enable Aster actions in the Android app for this session",
            )
        }
        val appliedAt = Instant.now().toString()
        val next = AsterRoomExpressionState(
            expression = expression,
            caption = caption,
            // The bearer-authenticated path proves MCP tool input, not which person or model
            // originated it. The Room must not silently promote transport into identity.
            author = ExpressionAuthor.MCP,
            authoredAt = authoredAt,
            appliedAt = appliedAt,
            authoredEventId = authoredEventId,
            appliedEventId = UUID.randomUUID().toString(),
        )
        expressionState = next
        uiListener?.onRoomExpression(next)
        onActivity("Authenticated MCP authored the ${expression.wireName} room expression")
        return RoomExpressionApplyResult(next)
    }

    val state: ConnectionState
        get() = if (initialized) client.state else ConnectionState.DISCONNECTED

    val stateDetail: String
        get() = if (initialized) client.stateDetail else "Disconnected"

    override fun onConnectionState(state: ConnectionState, detail: String) {
        if (state == ConnectionState.DISCONNECTED) {
            disableSubmissions("Aster actions disabled because the relay disconnected")
        }
        uiListener?.onConnectionState(state, detail)
    }

    override fun onActivity(message: String) {
        uiListener?.onActivity(message)
    }

    private fun disableSubmissions(message: String) {
        val wasEnabled = submissionsEnabled || submissionExpiresAtElapsedMs != 0L
        mainHandler.removeCallbacks(submissionExpiryRunnable)
        submissionExpiresAtElapsedMs = 0L
        if (wasEnabled) onActivity(message)
    }

    private const val SUBMISSION_AUTHORIZATION_MS = 15L * 60L * 1000L
}
