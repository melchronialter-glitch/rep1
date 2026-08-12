package dev.aster.rosytalkbridge

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Stores only AES/GCM ciphertext in SharedPreferences; the AES key never leaves Keystore. */
class SecureTokenStore(context: Context) {
    private val appContext = context.applicationContext
    private val preferences = appContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val associatedData = appContext.packageName.toByteArray(StandardCharsets.UTF_8)

    fun loadToken(): String? {
        val encodedIv = preferences.getString(KEY_IV, null) ?: return null
        val encodedCiphertext = preferences.getString(KEY_CIPHERTEXT, null) ?: return null
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            val iv = Base64.decode(encodedIv, Base64.NO_WRAP)
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(GCM_TAG_BITS, iv))
            cipher.updateAAD(associatedData)
            val plaintext = cipher.doFinal(Base64.decode(encodedCiphertext, Base64.NO_WRAP))
            String(plaintext, StandardCharsets.UTF_8)
        } catch (_: Exception) {
            clear()
            deleteKey()
            null
        }
    }

    fun saveToken(token: String) {
        if (token.isEmpty()) {
            clear()
            return
        }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        cipher.updateAAD(associatedData)
        val ciphertext = cipher.doFinal(token.toByteArray(StandardCharsets.UTF_8))
        preferences.edit()
            .putString(KEY_IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString(KEY_CIPHERTEXT, Base64.encodeToString(ciphertext, Base64.NO_WRAP))
            .apply()
    }

    fun clear() {
        preferences.edit().remove(KEY_IV).remove(KEY_CIPHERTEXT).apply()
    }

    private fun deleteKey() {
        try {
            KeyStore.getInstance(ANDROID_KEYSTORE).apply {
                load(null)
                if (containsAlias(KEY_ALIAS)) deleteEntry(KEY_ALIAS)
            }
        } catch (_: Exception) {
            // A later save surfaces an unavailable Keystore to the UI.
        }
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE).run {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            generateKey()
        }
    }

    private companion object {
        const val PREFERENCES_NAME = "secure_phone_token"
        const val KEY_IV = "iv"
        const val KEY_CIPHERTEXT = "ciphertext"
        const val KEY_ALIAS = "aster_rosytalk_bridge_phone_token_v1"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val GCM_TAG_BITS = 128
    }
}
