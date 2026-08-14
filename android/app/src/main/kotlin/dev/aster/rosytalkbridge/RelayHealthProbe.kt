package dev.aster.rosytalkbridge

import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.net.UnknownServiceException
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException

internal data class RelayHealthResult(
    val healthy: Boolean,
    val message: String,
)

/** Token-free HTTP reachability probe for the relay's public /healthz endpoint. */
internal class RelayHealthProbe {
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .callTimeout(8, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .build()
    private val lock = Any()
    private var currentCall: Call? = null

    fun probe(endpoint: RelayEndpoint, callback: (RelayHealthResult) -> Unit) {
        val request = Request.Builder()
            .url(endpoint.healthUrl)
            .header("Accept", "application/json")
            .get()
            .build()
        val call = client.newCall(request)
        synchronized(lock) {
            currentCall?.cancel()
            currentCall = call
        }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, error: IOException) {
                if (!finish(call) || call.isCanceled()) return
                callback(failureResult(endpoint.displayEndpoint, error))
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!finish(call)) return
                    val code = response.code
                    val result = when {
                        code in 200..299 && responseHasBoundedOk(response) -> RelayHealthResult(
                            healthy = true,
                            message = "Relay health endpoint verified at ${endpoint.displayEndpoint} (HTTP $code, ok=true). The network path is open; Connect will next verify WebSocket authentication.",
                        )
                        code in 200..299 -> RelayHealthResult(
                            healthy = false,
                            message = "A server was reached at ${endpoint.displayEndpoint} (HTTP $code), but /healthz did not return the relay's bounded ok=true response. Check that this is the RosyTalk relay port.",
                        )
                        code == 401 -> RelayHealthResult(
                            healthy = false,
                            message = "A server was reached at ${endpoint.displayEndpoint}, but /healthz unexpectedly requires authentication (HTTP 401). Check any proxy in front of the relay.",
                        )
                        code == 403 -> RelayHealthResult(
                            healthy = false,
                            message = "A server was reached at ${endpoint.displayEndpoint}, but it rejected this host (HTTP 403). Check the relay ALLOWED_HOSTS and the exact laptop address.",
                        )
                        code == 404 -> RelayHealthResult(
                            healthy = false,
                            message = "A server was reached at ${endpoint.displayEndpoint}, but /healthz was not found (HTTP 404). Check that this is the RosyTalk relay port.",
                        )
                        code >= 500 -> RelayHealthResult(
                            healthy = false,
                            message = "A server was reached at ${endpoint.displayEndpoint}, but its health endpoint failed (HTTP $code). Inspect the relay window.",
                        )
                        else -> RelayHealthResult(
                            healthy = false,
                            message = "A server was reached at ${endpoint.displayEndpoint}, but /healthz returned HTTP $code. Check the relay or proxy configuration.",
                        )
                    }
                    callback(result)
                }
            }
        })
    }

    fun cancel() {
        synchronized(lock) {
            currentCall?.cancel()
            currentCall = null
        }
    }

    private fun finish(call: Call): Boolean = synchronized(lock) {
        if (currentCall !== call) return@synchronized false
        currentCall = null
        true
    }

    private fun responseHasBoundedOk(response: Response): Boolean {
        return try {
            val bytes = response.peekBody(MAX_HEALTH_BODY_BYTES + 1L).bytes()
            if (bytes.size > MAX_HEALTH_BODY_BYTES) {
                false
            } else {
                val value = JSONObject(String(bytes, StandardCharsets.UTF_8))
                value.opt("ok") == true
            }
        } catch (_: Exception) {
            false
        }
    }

    private fun failureResult(endpoint: String, error: Throwable): RelayHealthResult {
        val cause = error.causes().firstOrNull { candidate ->
            candidate is UnknownHostException ||
                candidate is NoRouteToHostException ||
                candidate is ConnectException ||
                candidate is SocketTimeoutException ||
                candidate is SSLException ||
                candidate is UnknownServiceException
        } ?: error
        val message = when (cause) {
            is UnknownHostException ->
                "The relay host at $endpoint could not be resolved. Check the entered laptop address."
            is NoRouteToHostException ->
                "No network route reaches $endpoint. Put the phone and laptop on the same trusted Wi-Fi and check client isolation."
            is ConnectException ->
                "TCP connection to $endpoint failed before token authentication. Check the exact laptop IP and port, keep the relay window open, and allow Node.js through Windows Firewall on Private networks."
            is SocketTimeoutException ->
                "The network connection to $endpoint timed out before token authentication. Check Wi-Fi isolation, firewall, and the laptop address."
            is SSLException ->
                "The secure connection to $endpoint failed during TLS setup. Check the relay certificate and wss:// endpoint."
            is UnknownServiceException ->
                "Android rejected the connection type for $endpoint. Use this debug build only for trusted-LAN ws://, or configure wss://."
            else ->
                "The health check to $endpoint failed before WebSocket authentication. Check the laptop address, relay window, firewall, and phone network."
        }
        return RelayHealthResult(healthy = false, message = message)
    }

    private fun Throwable.causes(): Sequence<Throwable> = sequence {
        val seen = HashSet<Throwable>()
        var current: Throwable? = this@causes
        while (current != null && seen.add(current)) {
            yield(current)
            current = current.cause
        }
    }

    private companion object {
        const val MAX_HEALTH_BODY_BYTES = 4 * 1024
    }
}
