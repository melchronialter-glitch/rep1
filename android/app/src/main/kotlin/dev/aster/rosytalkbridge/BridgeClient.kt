package dev.aster.rosytalkbridge

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Build
import android.os.Handler
import android.os.Looper
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.URI
import java.net.UnknownHostException
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import javax.net.ssl.SSLException
import kotlin.math.floor

/** Outbound-only protocol-v2 WebSocket client for the relay's authenticated /phone endpoint. */
class BridgeClient(
    context: Context,
    private val listener: BridgeListener,
) {
    private val appContext = context.applicationContext
    private val debugBuild =
        appContext.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
    private val mainHandler = Handler(Looper.getMainLooper())
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(30, TimeUnit.SECONDS)
        .build()
    private val pendingRequests = AtomicInteger(0)
    private val lock = Any()
    private val sendLock = Any()

    @Volatile
    private var connectionState = ConnectionState.DISCONNECTED

    @Volatile
    private var detail = "Disconnected"

    private var activeGeneration = 0L
    private var currentSocket: WebSocket? = null
    private var lastUrl: String? = null
    private var lastToken: String? = null

    val isActive: Boolean
        get() = connectionState != ConnectionState.DISCONNECTED

    val state: ConnectionState
        get() = connectionState

    val stateDetail: String
        get() = detail

    fun connect(rawUrl: String, phoneToken: String) {
        val normalizedUrl = normalizeRelayUrl(rawUrl)
        if (phoneToken.isBlank()) throw IllegalArgumentException("Phone token is required")
        if (phoneToken.length > MAX_TOKEN_CHARACTERS) {
            throw IllegalArgumentException("Phone token is unexpectedly long")
        }
        val targetPackage = BridgePreferences.targetPackage(appContext)
        if (targetPackage.isBlank()) {
            throw IllegalArgumentException("Select the RosyTalk app first")
        }
        if (targetPackage == appContext.packageName) {
            throw IllegalArgumentException("The bridge cannot target itself")
        }

        val request = Request.Builder()
            .url(normalizedUrl)
            .header("Authorization", "Bearer $phoneToken")
            .build()
        lastUrl = normalizedUrl
        lastToken = phoneToken

        val (previous, generation) = synchronized(lock) {
            val oldSocket = currentSocket
            currentSocket = null
            activeGeneration += 1
            connectionState = ConnectionState.CONNECTING
            detail = "Connecting to relay…"
            oldSocket to activeGeneration
        }
        previous?.close(CLOSE_NORMAL, "Client reconnecting")
        listener.onConnectionState(ConnectionState.CONNECTING, detail)
        listener.onActivity("Opening an authenticated outbound relay connection")

        val socket = httpClient.newWebSocket(request, RelaySocketListener(generation))
        synchronized(lock) {
            if (activeGeneration == generation) {
                currentSocket = socket
            } else {
                socket.close(CLOSE_NORMAL, "Superseded")
            }
        }
    }

    fun refreshCapabilities() {
        val url = lastUrl ?: return
        val token = lastToken ?: return
        if (!isActive) return
        try {
            connect(url, token)
        } catch (_: Exception) {
            listener.onActivity("Could not refresh relay capabilities")
        }
    }

    fun disconnect(newDetail: String = "Disconnected") {
        val socket = synchronized(lock) {
            activeGeneration += 1
            val oldSocket = currentSocket
            currentSocket = null
            connectionState = ConnectionState.DISCONNECTED
            detail = newDetail
            oldSocket
        }
        socket?.close(CLOSE_NORMAL, "Disconnected by user")
        listener.onConnectionState(ConnectionState.DISCONNECTED, newDetail)
        listener.onActivity(newDetail)
    }

    fun publishSnapshot(snapshot: ConversationSnapshot) {
        val active = synchronized(lock) {
            if (connectionState != ConnectionState.READY) null
            else currentSocket?.let { it to activeGeneration }
        } ?: return
        val event = JSONObject()
            .put("type", "event")
            .put("event", "chat.updated")
            .put("snapshot", snapshot.toJson())
        if (!sendIfCurrent(active.first, active.second, event, allowBusyError = false)) {
            listener.onActivity("Dropped a chat.updated event because the relay queue was busy")
        }
    }

    private inner class RelaySocketListener(
        private val generation: Long,
    ) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (!isGenerationActive(generation)) {
                webSocket.close(CLOSE_NORMAL, "Superseded")
                return
            }
            if (!webSocket.send(createHello().toString())) {
                webSocket.close(CLOSE_PROTOCOL_ERROR, "Hello could not be sent")
                finishGeneration(generation)
                updateState(ConnectionState.DISCONNECTED, "Could not send phone hello")
                return
            }

            synchronized(lock) {
                if (activeGeneration != generation) return
                connectionState = ConnectionState.READY
                detail = "Connected and ready"
            }
            listener.onConnectionState(ConnectionState.READY, "Connected and ready")
            listener.onActivity("Protocol v2 hello sent; scoped chat requests are ready")
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (!isGenerationActive(generation)) return
            val request = try {
                JSONObject(text)
            } catch (_: Exception) {
                listener.onActivity("Ignored malformed relay JSON")
                return
            }
            if (request.optString("type") != "request") {
                listener.onActivity("Ignored a non-request relay message")
                return
            }

            val id = request.optString("id")
            if (!isCanonicalUuid(id)) {
                listener.onActivity("Ignored a request with an invalid identifier")
                return
            }
            val method = request.optString("method")
            val params = request.optJSONObject("params") ?: JSONObject()
            if (pendingRequests.incrementAndGet() > MAX_PENDING_REQUESTS) {
                pendingRequests.decrementAndGet()
                sendIfCurrent(
                    webSocket,
                    generation,
                    errorResponse(id, "PHONE_BUSY", "The phone request queue is full"),
                )
                listener.onActivity("Rejected a relay request (PHONE_BUSY)")
                return
            }
            dispatchRequest(webSocket, generation, id, method, params)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            if (isGenerationActive(generation)) {
                listener.onActivity("Relay is closing the connection (code $code)")
            }
            webSocket.close(code, null)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            if (!finishGeneration(generation)) return
            updateState(ConnectionState.DISCONNECTED, "Relay disconnected (code $code)")
            listener.onActivity("Relay connection closed")
        }

        override fun onFailure(webSocket: WebSocket, error: Throwable, response: Response?) {
            val responseCode = response?.code
            response?.close()
            if (!finishGeneration(generation)) return
            val failureDetail = friendlyFailure(error, responseCode)
            updateState(ConnectionState.DISCONNECTED, failureDetail)
            listener.onActivity(failureDetail)
        }
    }

    private fun dispatchRequest(
        socket: WebSocket,
        generation: Long,
        id: String,
        method: String,
        params: JSONObject,
    ) {
        val loggedMethod = method.take(MAX_LOGGED_METHOD)
        listener.onActivity("Received $loggedMethod")
        val parsed = try {
            when (method) {
                "chat.snapshot" -> PendingOperation.Snapshot(optionalInt(params, "maxItems", 100, 1, 200))
                "chat.submit" -> PendingOperation.Submit(
                    text = requiredString(params, "text"),
                    expectedRevision = requiredLong(
                        params,
                        "expectedRevision",
                        0L,
                        RosyTalkAccessibilityService.MAX_SAFE_REVISION,
                    ),
                    expectedSnapshotId = requiredUuid(params, "expectedSnapshotId"),
                )
                "room.expression" -> PendingOperation.Expression(
                    expression = requiredExpression(params, "state"),
                    caption = optionalBoundedString(params, "caption", MAX_EXPRESSION_CAPTION),
                    authoredAt = requiredInstant(params, "authoredAt"),
                    authoredEventId = requiredUuid(params, "authoredEventId"),
                )
                else -> throw BridgeException("METHOD_NOT_FOUND", "Unsupported phone method")
            }
        } catch (error: BridgeException) {
            pendingRequests.decrementAndGet()
            sendIfCurrent(socket, generation, errorResponse(id, error.code, error.message))
            listener.onActivity("Rejected $loggedMethod (${error.code})")
            return
        }

        mainHandler.post {
            try {
                if (!isGenerationActive(generation)) return@post
                val result = when (parsed) {
                    is PendingOperation.Expression -> BridgeRuntime.applyRemoteRoomExpression(
                        expression = parsed.expression,
                        caption = parsed.caption,
                        authoredAt = parsed.authoredAt,
                        authoredEventId = parsed.authoredEventId,
                    ).toJson()
                    is PendingOperation.Snapshot -> requireAccessibilityService()
                        .captureSnapshot(parsed.maxItems)
                        .also(BridgeRuntime::mirrorSnapshot)
                        .toJson()
                    is PendingOperation.Submit -> requireAccessibilityService()
                        .submitText(
                            parsed.text,
                            parsed.expectedRevision,
                            parsed.expectedSnapshotId,
                        ).toJson()
                }
                if (sendIfCurrent(socket, generation, successResponse(id, result))) {
                    listener.onActivity("Completed $loggedMethod")
                }
            } catch (error: BridgeException) {
                sendIfCurrent(socket, generation, errorResponse(id, error.code, error.message))
                listener.onActivity("Rejected $loggedMethod (${error.code})")
            } catch (_: Exception) {
                sendIfCurrent(
                    socket,
                    generation,
                    errorResponse(id, "INTERNAL_ERROR", "The phone could not complete the chat request"),
                )
                listener.onActivity("Failed $loggedMethod (INTERNAL_ERROR)")
            } finally {
                pendingRequests.decrementAndGet()
            }
        }
    }

    private fun createHello(): JSONObject {
        val installDeviceId = BridgePreferences.installDeviceId(appContext)
        val modelName = listOf(Build.MANUFACTURER, Build.MODEL)
            .filter { it.isNotBlank() }
            .joinToString(" ")
            .ifBlank { "Android phone" }
        val versionName = try {
            appContext.packageManager.getPackageInfo(appContext.packageName, 0).versionName
        } catch (_: Exception) {
            null
        } ?: "0.3.0"
        val androidVersion = Build.VERSION.RELEASE?.takeIf { it.isNotBlank() }
            ?: Build.VERSION.SDK_INT.toString()
        val targetPackage = BridgePreferences.targetPackage(appContext)
        val accessibilityEnabled =
            targetPackage.isNotBlank() && RosyTalkAccessibilityService.current != null

        return JSONObject()
            .put("type", "hello")
            .put("protocolVersion", PROTOCOL_VERSION)
            .put(
                "device",
                JSONObject()
                    .put("id", installDeviceId.take(MAX_DEVICE_FIELD))
                    .put("name", modelName.take(MAX_DEVICE_FIELD))
                    .put("appVersion", versionName.take(MAX_VERSION_FIELD))
                    .put("androidVersion", androidVersion.take(MAX_VERSION_FIELD)),
            )
            .put(
                "capabilities",
                JSONObject()
                    .put(
                        "targetPackage",
                        targetPackage.takeIf { it.isNotBlank() } ?: JSONObject.NULL,
                    )
                    .put("accessibilityEnabled", accessibilityEnabled)
                    .put("canReadVisible", accessibilityEnabled)
                    .put("submissionsEnabled", BridgeRuntime.submissionsEnabled)
                    // Feature support and the live action arm are distinct. The relay requires
                    // both canSetExpression and submissionsEnabled before dispatch.
                    .put("canSetExpression", true)
                    .put(
                        "canSubmit",
                        accessibilityEnabled && BridgeRuntime.submissionsEnabled,
                    ),
            )
    }

    private fun requireAccessibilityService(): RosyTalkAccessibilityService =
        RosyTalkAccessibilityService.current
            ?: throw BridgeException(
                "ACCESSIBILITY_UNAVAILABLE",
                "Enable the RosyTalk bridge in Android Accessibility settings",
            )

    private fun successResponse(id: String, result: JSONObject): JSONObject = JSONObject()
        .put("type", "response")
        .put("id", id)
        .put("ok", true)
        .put("result", result)

    private fun errorResponse(id: String, code: String, message: String): JSONObject = JSONObject()
        .put("type", "response")
        .put("id", id)
        .put("ok", false)
        .put(
            "error",
            JSONObject()
                .put("code", code.take(MAX_ERROR_CODE))
                .put("message", message.take(MAX_ERROR_MESSAGE)),
        )

    private fun sendIfCurrent(
        socket: WebSocket,
        generation: Long,
        messageObject: JSONObject,
        allowBusyError: Boolean = true,
    ): Boolean {
        if (!isGenerationActive(generation)) return false
        val message = messageObject.toString()
        val messageBytes = message.toByteArray(StandardCharsets.UTF_8).size.toLong()
        return synchronized(sendLock) {
            if (!isGenerationActive(generation)) return@synchronized false
            if (socket.queueSize() > MAX_WEBSOCKET_QUEUE_BYTES - messageBytes) {
                if (allowBusyError) {
                    val id = messageObject.optString("id")
                    if (messageObject.optBoolean("ok", false) && isCanonicalUuid(id)) {
                        val busy = errorResponse(
                            id,
                            "PHONE_BUSY",
                            "Wait for the previous phone response before trying again",
                        ).toString()
                        if (socket.queueSize() + busy.toByteArray(StandardCharsets.UTF_8).size <=
                            MAX_WEBSOCKET_QUEUE_BYTES
                        ) {
                            socket.send(busy)
                        }
                    }
                }
                return@synchronized false
            }
            socket.send(message)
        }
    }

    private fun requiredString(params: JSONObject, key: String): String {
        val value = if (!params.has(key) || params.isNull(key)) null else params.opt(key)
        if (value !is String || value.isBlank() || value.length > RosyTalkAccessibilityService.MAX_MESSAGE_CHARACTERS) {
            throw BridgeException(
                "INVALID_PARAMS",
                "$key must contain 1 to ${RosyTalkAccessibilityService.MAX_MESSAGE_CHARACTERS} characters",
            )
        }
        return value
    }

    private fun optionalInt(
        params: JSONObject,
        key: String,
        defaultValue: Int,
        minimum: Int,
        maximum: Int,
    ): Int {
        if (!params.has(key) || params.isNull(key)) return defaultValue
        val value = params.opt(key) as? Number
            ?: throw BridgeException("INVALID_PARAMS", "$key must be an integer")
        val number = value.toDouble()
        if (!number.isFinite() || floor(number) != number || number < minimum || number > maximum) {
            throw BridgeException("INVALID_PARAMS", "$key is outside the allowed range")
        }
        return number.toInt()
    }

    private fun requiredLong(
        params: JSONObject,
        key: String,
        minimum: Long,
        maximum: Long,
    ): Long {
        if (!params.has(key) || params.isNull(key)) {
            throw BridgeException("INVALID_PARAMS", "$key is required")
        }
        val value = params.opt(key) as? Number
            ?: throw BridgeException("INVALID_PARAMS", "$key must be an integer")
        val number = value.toDouble()
        if (!number.isFinite() || floor(number) != number || number < minimum || number > maximum) {
            throw BridgeException("INVALID_PARAMS", "$key is outside the allowed range")
        }
        return number.toLong()
    }

    private fun requiredUuid(params: JSONObject, key: String): String {
        val value = requiredString(params, key)
        if (!isCanonicalUuid(value)) {
            throw BridgeException("INVALID_PARAMS", "$key must be a canonical UUID")
        }
        return value
    }

    private fun requiredExpression(params: JSONObject, key: String): AsterExpression {
        val value = requiredString(params, key)
        return AsterExpression.fromWireName(value)
            ?: throw BridgeException(
                "INVALID_PARAMS",
                "$key must be one of neutral, thinking, amused, soft, fierce, flustered, or blush",
            )
    }

    private fun optionalBoundedString(params: JSONObject, key: String, maximum: Int): String? {
        if (!params.has(key) || params.isNull(key)) return null
        val value = params.opt(key) as? String
            ?: throw BridgeException("INVALID_PARAMS", "$key must be a string or null")
        if (value.length > maximum || value.trim().isEmpty()) {
            throw BridgeException(
                "INVALID_PARAMS",
                "$key must contain 1 to $maximum characters when present",
            )
        }
        // Preserve the exact authored value so the acknowledgement matches relay ancestry.
        return value
    }

    private fun requiredInstant(params: JSONObject, key: String): String {
        val value = requiredString(params, key)
        if (value.length > MAX_AUTHORED_AT) {
            throw BridgeException("INVALID_PARAMS", "$key is unexpectedly long")
        }
        return try {
            Instant.parse(value).toString()
        } catch (_: Exception) {
            throw BridgeException("INVALID_PARAMS", "$key must be an ISO-8601 instant")
        }
    }

    private fun normalizeRelayUrl(rawUrl: String): String {
        val uri = try {
            URI(rawUrl.trim())
        } catch (_: Exception) {
            throw IllegalArgumentException("Relay URL is invalid")
        }
        val scheme = uri.scheme?.lowercase()
        if (scheme != "ws" && scheme != "wss") {
            throw IllegalArgumentException("Relay URL must use ws:// or wss://")
        }
        if (!debugBuild && scheme != "wss") {
            throw IllegalArgumentException("Release builds require a wss:// relay URL")
        }
        if (uri.host.isNullOrBlank() || uri.userInfo != null || uri.query != null || uri.fragment != null) {
            throw IllegalArgumentException("Relay URL must contain only a host, port, and /phone path")
        }
        val path = uri.path.orEmpty()
        if (path.isNotEmpty() && path != "/" && path != PHONE_PATH && path != "$PHONE_PATH/") {
            throw IllegalArgumentException("Relay URL path must be /phone")
        }
        return try {
            URI(scheme, null, uri.host, uri.port, PHONE_PATH, null, null).toASCIIString()
        } catch (_: Exception) {
            throw IllegalArgumentException("Relay URL is invalid")
        }
    }

    private fun isCanonicalUuid(value: String): Boolean = try {
        UUID.fromString(value).toString().equals(value, ignoreCase = true)
    } catch (_: IllegalArgumentException) {
        false
    }

    private fun isGenerationActive(generation: Long): Boolean =
        synchronized(lock) { activeGeneration == generation }

    private fun finishGeneration(generation: Long): Boolean = synchronized(lock) {
        if (activeGeneration != generation) return@synchronized false
        activeGeneration += 1
        currentSocket = null
        connectionState = ConnectionState.DISCONNECTED
        true
    }

    private fun updateState(newState: ConnectionState, newDetail: String) {
        connectionState = newState
        detail = newDetail
        listener.onConnectionState(newState, newDetail)
    }

    private fun friendlyFailure(error: Throwable, responseCode: Int?): String {
        if (responseCode == 401 || responseCode == 403) return "Relay rejected the phone token"
        return when (error) {
            is UnknownHostException -> "Relay host was not found"
            is ConnectException -> "Could not reach the relay"
            is SocketTimeoutException -> "Relay connection timed out"
            is SSLException -> "Secure relay handshake failed"
            else -> "Relay WebSocket connection failed"
        }
    }

    private sealed interface PendingOperation {
        data class Snapshot(val maxItems: Int) : PendingOperation
        data class Submit(
            val text: String,
            val expectedRevision: Long,
            val expectedSnapshotId: String,
        ) : PendingOperation
        data class Expression(
            val expression: AsterExpression,
            val caption: String?,
            val authoredAt: String,
            val authoredEventId: String,
        ) : PendingOperation
    }

    private companion object {
        const val PROTOCOL_VERSION = 2
        const val PHONE_PATH = "/phone"
        const val CLOSE_NORMAL = 1000
        const val CLOSE_PROTOCOL_ERROR = 1002
        const val MAX_TOKEN_CHARACTERS = 8192
        const val MAX_DEVICE_FIELD = 200
        const val MAX_VERSION_FIELD = 50
        const val MAX_ERROR_CODE = 100
        const val MAX_ERROR_MESSAGE = 1000
        const val MAX_LOGGED_METHOD = 80
        const val MAX_EXPRESSION_CAPTION = 160
        const val MAX_AUTHORED_AT = 80
        const val MAX_PENDING_REQUESTS = 8
        const val MAX_WEBSOCKET_QUEUE_BYTES = 8L * 1024L * 1024L
    }
}
