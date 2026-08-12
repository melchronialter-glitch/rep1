package dev.aster.rosytalkbridge

import android.app.Activity
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.text.method.PasswordTransformationMethod
import android.text.method.ScrollingMovementMethod
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : Activity(), BridgeListener {
    private lateinit var relayUrlInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var targetSpinner: Spinner
    private lateinit var accessibilityText: TextView
    private lateinit var submissionsSwitch: Switch
    private lateinit var connectButton: Button
    private lateinit var disconnectButton: Button
    private lateinit var statusText: TextView
    private lateinit var logText: TextView
    private lateinit var secureTokenStore: SecureTokenStore
    private lateinit var appChoices: List<AppChoice>
    private val logLines = ArrayDeque<String>()
    private val timestampFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private var restoringSpinner = true
    private var suppressSubmissionListener = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        secureTokenStore = SecureTokenStore(this)
        BridgeRuntime.initialize(applicationContext)
        setContentView(createContentView())
        restoreSettings()
        installListeners()
        // This authorization is intentionally neither stored nor inherited by a newly opened
        // setup Activity. The user has to turn it on again for the current session.
        submissionsSwitch.isChecked = false
        submissionsSwitch.isSaveEnabled = false
        BridgeRuntime.setSubmissionsEnabled(false)
        updateConnectionControls(BridgeRuntime.state)
        appendLog("Session started; message submission is off")
    }

    override fun onStart() {
        super.onStart()
        BridgeRuntime.attach(this)
    }

    override fun onResume() {
        super.onResume()
        refreshAccessibilityDisplay()
        reflectSubmissionAuthorization()
    }

    override fun onStop() {
        persistSettings()
        BridgeRuntime.detach(this)
        super.onStop()
    }

    override fun onConnectionState(state: ConnectionState, detail: String) {
        runOnUiThread {
            statusText.text = detail
            updateConnectionControls(state)
        }
    }

    override fun onActivity(message: String) {
        runOnUiThread {
            reflectSubmissionAuthorization()
            appendLog(message)
        }
    }

    private fun createContentView(): View {
        val scrollView = ScrollView(this).apply { isFillViewport = true }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20.dp, 24.dp, 20.dp, 28.dp)
        }
        scrollView.addView(content, matchWrap())

        content.addView(heading("Aster RosyTalk Bridge", 26f))
        content.addView(
            body(
                "A direct, package-scoped bridge for the visible RosyTalk conversation. " +
                    "It does not read notifications, the clipboard, files, or any other app window.",
            ).withBottomMargin(18.dp),
        )

        content.addView(label("Target app"))
        targetSpinner = Spinner(this)
        content.addView(targetSpinner, matchWrap())
        content.addView(
            body(
                "Android is restricted to this exact package. Visible items are an incomplete " +
                    "window snapshot; sender labels based on left/right position remain explicit inferences.",
                13f,
            ).withBottomMargin(16.dp),
        )

        content.addView(label("Relay WebSocket URL"))
        relayUrlInput = EditText(this).apply {
            hint = "wss://relay.example/phone"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
        }
        content.addView(relayUrlInput, matchWrap())

        content.addView(label("Phone token").withTopMargin(14.dp))
        tokenInput = EditText(this).apply {
            hint = "Bearer phone token"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            transformationMethod = PasswordTransformationMethod.getInstance()
            setSingleLine(true)
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            contentDescription = "Phone token, masked"
        }
        content.addView(tokenInput, matchWrap())
        content.addView(
            body("The saved token is AES/GCM ciphertext backed by Android Keystore.", 13f)
                .withBottomMargin(14.dp),
        )

        val connectionButtons = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        connectButton = Button(this).apply { text = "Connect" }
        disconnectButton = Button(this).apply { text = "Disconnect" }
        connectionButtons.addView(connectButton, weightedButton())
        connectionButtons.addView(disconnectButton, weightedButton(leftMargin = 8.dp))
        content.addView(connectionButtons, matchWrap())

        content.addView(sectionDivider())
        content.addView(heading("Android access", 20f))
        accessibilityText = body("")
        content.addView(accessibilityText.withBottomMargin(8.dp))
        val accessibilityButton = Button(this).apply { text = "Open Accessibility settings" }
        accessibilityButton.setOnClickListener {
            appendLog("Opening Android Accessibility settings")
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        content.addView(accessibilityButton, matchWrap())

        submissionsSwitch = Switch(this).apply {
            text = "Allow message submission for 15 minutes"
            textSize = 16f
            isChecked = false
        }
        content.addView(submissionsSwitch, matchWrap().apply { topMargin = 16.dp })
        content.addView(
            body(
                "Off on launch and automatically expires. When enabled, the bridge may set the visible message field and " +
                    "activate one unambiguous Send control. It never treats that as delivery confirmation.",
                13f,
            ),
        )

        content.addView(sectionDivider())
        content.addView(heading("Status", 20f))
        statusText = TextView(this).apply {
            text = BridgeRuntime.stateDetail
            textSize = 17f
            setTextColor(Color.rgb(25, 46, 89))
            setPadding(12.dp, 12.dp, 12.dp, 12.dp)
            setBackgroundColor(Color.rgb(235, 240, 252))
        }
        content.addView(statusText, matchWrap().apply { bottomMargin = 16.dp })

        content.addView(heading("Activity log", 18f))
        logText = TextView(this).apply {
            textSize = 13f
            typeface = android.graphics.Typeface.MONOSPACE
            setTextColor(Color.rgb(32, 32, 32))
            setPadding(12.dp, 12.dp, 12.dp, 12.dp)
            setBackgroundColor(Color.rgb(245, 245, 245))
            movementMethod = ScrollingMovementMethod.getInstance()
            maxLines = 16
            minLines = 7
        }
        content.addView(logText, matchWrap())
        content.addView(
            body(
                "This log is ephemeral and never includes credentials or conversation text.",
                12f,
            ).withTopMargin(8.dp),
        )
        return scrollView
    }

    private fun restoreSettings() {
        appChoices = launchableApps()
        val adapter = ArrayAdapter(this, android.R.layout.simple_spinner_item, appChoices).apply {
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        }
        targetSpinner.adapter = adapter
        val savedPackage = BridgePreferences.targetPackage(this)
        val savedIndex = appChoices.indexOfFirst { it.packageName == savedPackage }
        targetSpinner.setSelection(if (savedIndex >= 0) savedIndex else 0, false)
        restoringSpinner = false

        val debugBuild = applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
        val defaultUrl = if (debugBuild) "ws://10.0.2.2:8787/phone" else ""
        relayUrlInput.setText(BridgePreferences.relayUrl(this, defaultUrl))
        tokenInput.setText(secureTokenStore.loadToken().orEmpty())
    }

    private fun installListeners() {
        targetSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (restoringSpinner) return
                val selected = appChoices.getOrNull(position)?.packageName.orEmpty()
                BridgePreferences.saveTargetPackage(this@MainActivity, selected)
                BridgeRuntime.targetConfigurationChanged()
                refreshAccessibilityDisplay()
                appendLog(if (selected.isBlank()) "Target app cleared" else "Target app changed")
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }
        connectButton.setOnClickListener { connectFromUi() }
        disconnectButton.setOnClickListener { BridgeRuntime.disconnect("Disconnected by user") }
        submissionsSwitch.setOnCheckedChangeListener { _, enabled ->
            if (!suppressSubmissionListener) BridgeRuntime.setSubmissionsEnabled(enabled)
        }
    }

    private fun connectFromUi() {
        persistSelectedTarget()
        val targetPackage = BridgePreferences.targetPackage(this)
        if (targetPackage.isBlank()) {
            showInputError("Select the RosyTalk app")
            return
        }
        if (RosyTalkAccessibilityService.current == null) {
            showInputError("Enable the RosyTalk bridge in Android Accessibility settings")
            return
        }
        val url = relayUrlInput.text.toString().trim()
        val token = tokenInput.text.toString()
        if (url.isBlank()) {
            showInputError("Enter the relay WebSocket URL")
            return
        }
        if (token.isBlank()) {
            showInputError("Enter the phone token")
            return
        }
        if (!persistTokenIfPossible()) {
            showInputError("The phone token could not be stored securely")
            return
        }
        BridgePreferences.saveRelayUrl(this, url)
        try {
            BridgeRuntime.connect(url, token)
        } catch (error: IllegalArgumentException) {
            showInputError(error.message ?: "Relay settings are invalid")
        } catch (_: IllegalStateException) {
            showInputError("The connection client is unavailable")
        }
    }

    private fun persistSettings() {
        persistSelectedTarget()
        BridgePreferences.saveRelayUrl(this, relayUrlInput.text.toString())
        persistTokenIfPossible()
    }

    private fun persistSelectedTarget() {
        val selected = appChoices.getOrNull(targetSpinner.selectedItemPosition)?.packageName.orEmpty()
        if (selected != BridgePreferences.targetPackage(this)) {
            BridgePreferences.saveTargetPackage(this, selected)
            BridgeRuntime.targetConfigurationChanged()
        }
    }

    private fun persistTokenIfPossible(): Boolean = try {
        secureTokenStore.saveToken(tokenInput.text.toString())
        true
    } catch (_: Exception) {
        appendLog("Android Keystore could not save the phone token")
        false
    }

    private fun launchableApps(): List<AppChoice> {
        val launcherIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val resolved = if (Build.VERSION.SDK_INT >= 33) {
            packageManager.queryIntentActivities(
                launcherIntent,
                PackageManager.ResolveInfoFlags.of(0L),
            )
        } else {
            @Suppress("DEPRECATION")
            packageManager.queryIntentActivities(launcherIntent, 0)
        }
        val apps = resolved.mapNotNull { info ->
            val packageName = info.activityInfo?.packageName ?: return@mapNotNull null
            if (packageName == this.packageName) return@mapNotNull null
            val label = info.loadLabel(packageManager)?.toString()?.trim().orEmpty()
                .ifBlank { packageName }
            AppChoice(label, packageName)
        }.distinctBy { it.packageName }
            .sortedBy { it.label.lowercase(Locale.getDefault()) }
            .toMutableList()

        val savedPackage = BridgePreferences.targetPackage(this)
        if (savedPackage.isNotBlank() && apps.none { it.packageName == savedPackage }) {
            apps.add(0, AppChoice(savedPackage, savedPackage))
        }
        apps.add(0, AppChoice("Select an app…", ""))
        return apps
    }

    private fun refreshAccessibilityDisplay() {
        val selected = BridgePreferences.targetPackage(this)
        accessibilityText.text = when {
            selected.isBlank() -> "Select the target app first. Until then, the service is restricted to this bridge itself."
            RosyTalkAccessibilityService.current == null ->
                "Disabled — enable the service. Android will then deliver events only from the selected package."
            else -> "Enabled — window access is restricted to the selected package."
        }
    }

    private fun updateConnectionControls(state: ConnectionState) {
        connectButton.isEnabled = state != ConnectionState.CONNECTING
        disconnectButton.isEnabled = state != ConnectionState.DISCONNECTED
    }

    private fun reflectSubmissionAuthorization() {
        if (!::submissionsSwitch.isInitialized) return
        val enabled = BridgeRuntime.submissionsEnabled
        if (submissionsSwitch.isChecked == enabled) return
        suppressSubmissionListener = true
        submissionsSwitch.isChecked = enabled
        suppressSubmissionListener = false
    }

    private fun appendLog(message: String) {
        if (!::logText.isInitialized) return
        val timestamp = timestampFormat.format(Date())
        logLines.addLast("$timestamp  ${message.take(180)}")
        while (logLines.size > MAX_LOG_LINES) logLines.removeFirst()
        logText.text = logLines.joinToString("\n")
    }

    private fun showInputError(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        appendLog(message)
    }

    private fun heading(text: String, size: Float) = TextView(this).apply {
        this.text = text
        textSize = size
        setTextColor(Color.rgb(25, 25, 25))
    }

    private fun label(text: String) = TextView(this).apply {
        this.text = text
        textSize = 14f
        setTextColor(Color.rgb(55, 55, 55))
    }

    private fun body(text: String, size: Float = 15f) = TextView(this).apply {
        this.text = text
        textSize = size
        setTextColor(Color.rgb(70, 70, 70))
        setLineSpacing(0f, 1.15f)
    }

    private fun sectionDivider() = View(this).apply {
        setBackgroundColor(Color.rgb(220, 220, 220))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            1.dp,
        ).apply { setMargins(0, 24.dp, 0, 20.dp) }
    }

    private fun matchWrap() = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    )

    private fun weightedButton(leftMargin: Int = 0) = LinearLayout.LayoutParams(
        0,
        ViewGroup.LayoutParams.WRAP_CONTENT,
        1f,
    ).apply { this.leftMargin = leftMargin }

    private fun View.withTopMargin(margin: Int): View = apply {
        layoutParams = (layoutParams as? LinearLayout.LayoutParams ?: matchWrap()).apply {
            topMargin = margin
        }
    }

    private fun View.withBottomMargin(margin: Int): View = apply {
        layoutParams = (layoutParams as? LinearLayout.LayoutParams ?: matchWrap()).apply {
            bottomMargin = margin
        }
    }

    private val Int.dp: Int
        get() = (this * resources.displayMetrics.density).toInt()

    private data class AppChoice(val label: String, val packageName: String) {
        override fun toString(): String = if (packageName.isBlank()) label else "$label — $packageName"
    }

    private companion object {
        const val MAX_LOG_LINES = 80
    }
}
