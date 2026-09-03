package dev.aster.rosytalkbridge

import android.content.Context
import java.util.UUID

object BridgePreferences {
    private const val PREFERENCES_NAME = "rosytalk_bridge_settings"
    private const val KEY_RELAY_URL = "relay_url"
    private const val KEY_TARGET_PACKAGE = "target_package"
    private const val KEY_INSTALL_DEVICE_ID = "install_device_id"

    fun relayUrl(context: Context, fallback: String = ""): String =
        preferences(context).getString(KEY_RELAY_URL, fallback).orEmpty()

    fun saveRelayUrl(context: Context, value: String) {
        preferences(context).edit().putString(KEY_RELAY_URL, value.trim()).apply()
    }

    fun targetPackage(context: Context): String =
        preferences(context).getString(KEY_TARGET_PACKAGE, "").orEmpty()

    fun saveTargetPackage(context: Context, value: String) {
        preferences(context).edit().putString(KEY_TARGET_PACKAGE, value.trim()).apply()
    }

    fun installDeviceId(context: Context): String {
        val stored = preferences(context).getString(KEY_INSTALL_DEVICE_ID, null)
        if (!stored.isNullOrBlank()) return stored
        return synchronized(this) {
            val afterLock = preferences(context).getString(KEY_INSTALL_DEVICE_ID, null)
            if (!afterLock.isNullOrBlank()) return@synchronized afterLock
            UUID.randomUUID().toString().also { generated ->
                preferences(context).edit().putString(KEY_INSTALL_DEVICE_ID, generated).apply()
            }
        }
    }

    private fun preferences(context: Context) =
        context.applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
}
