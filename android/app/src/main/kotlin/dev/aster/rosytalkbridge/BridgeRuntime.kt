package dev.aster.rosytalkbridge

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock

enum class ConnectionState {
    DISCONNECTED,
    CONNECTING,
    READY,
}

interface BridgeListener {
    fun onConnectionState(state: ConnectionState, detail: String)
    fun onActivity(message: String)
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
                onActivity("Message submission authorization expired")
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
    }

    fun detach(listener: BridgeListener) {
        if (uiListener === listener) uiListener = null
    }

    fun connect(url: String, token: String) {
        check(initialized) { "Bridge runtime is not initialized" }
        client.connect(url, token)
    }

    fun disconnect(detail: String = "Disconnected") {
        disableSubmissions("Message submission disabled on disconnect")
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
                "Message submission enabled for 15 minutes"
            } else {
                "Message submission disabled"
            },
        )
        if (initialized && client.isActive) client.refreshCapabilities()
    }

    fun targetConfigurationChanged() {
        disableSubmissions("Message submission disabled because the target changed")
        RosyTalkAccessibilityService.current?.refreshPackageFilter()
        if (initialized && client.isActive) client.refreshCapabilities()
    }

    fun accessibilityStateChanged(enabled: Boolean) {
        if (!enabled) {
            disableSubmissions("Message submission disabled because Accessibility stopped")
        }
        if (initialized && client.isActive) client.refreshCapabilities()
    }

    fun publishSnapshot(snapshot: ConversationSnapshot) {
        if (initialized) client.publishSnapshot(snapshot)
    }

    val state: ConnectionState
        get() = if (initialized) client.state else ConnectionState.DISCONNECTED

    val stateDetail: String
        get() = if (initialized) client.stateDetail else "Disconnected"

    override fun onConnectionState(state: ConnectionState, detail: String) {
        if (state == ConnectionState.DISCONNECTED) {
            disableSubmissions("Message submission disabled because the relay disconnected")
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
