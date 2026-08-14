package dev.aster.rosytalkbridge

import android.app.Activity
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.text.method.PasswordTransformationMethod
import android.text.method.ScrollingMovementMethod
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
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
    private lateinit var relayGuidanceText: TextView
    private lateinit var tokenInput: EditText
    private lateinit var targetSpinner: Spinner
    private lateinit var accessibilityText: TextView
    private lateinit var submissionsSwitch: Switch
    private lateinit var connectButton: Button
    private lateinit var disconnectButton: Button
    private lateinit var testRelayButton: Button
    private lateinit var statusText: TextView
    private lateinit var logText: TextView
    private lateinit var asterFaceView: AsterFaceView
    private lateinit var expressionSpinner: Spinner
    private lateinit var expressionCaptionText: TextView
    private lateinit var expressionSourceText: TextView
    private lateinit var snapshotMetaText: TextView
    private lateinit var recentMessages: LinearLayout
    private lateinit var directPathText: TextView
    private lateinit var openRosyTalkButton: Button
    private lateinit var secureTokenStore: SecureTokenStore
    private val relayHealthProbe = RelayHealthProbe()
    private lateinit var appChoices: List<AppChoice>
    private val logLines = ArrayDeque<String>()
    private val timestampFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private var restoringSpinner = true
    private var suppressSubmissionListener = false
    private var suppressExpressionListener = false
    private var healthProbeActive = false
    private var relayDiagnosticMessage: String? = null
    private var relayDiagnosticFailed = false
    private var lastActivitySequence = 0L
    private var sessionStartLogged = false
    private val debugBuild: Boolean by lazy {
        applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
    }
    private val emulatorDevice: Boolean by lazy { isProbablyEmulator() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // The Room can display visible conversation text and credentials. Keep it out of
        // screenshots, screen recording, and Recents thumbnails by default.
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
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
        renderExpression(BridgeRuntime.currentRoomExpression)
        BridgeRuntime.latestSnapshot?.let(::renderSnapshot)
        refreshDirectPathDisplay()
    }

    override fun onStart() {
        super.onStart()
        BridgeRuntime.attach(this)
        if (!sessionStartLogged) {
            sessionStartLogged = true
            appendLog("Session started; Aster actions are off")
        }
    }

    override fun onResume() {
        super.onResume()
        refreshAccessibilityDisplay()
        reflectSubmissionAuthorization()
        refreshDirectPathDisplay()
    }

    override fun onStop() {
        persistSettings()
        BridgeRuntime.detach(this)
        super.onStop()
    }

    override fun onDestroy() {
        relayHealthProbe.cancel()
        super.onDestroy()
    }

    override fun onConnectionState(state: ConnectionState, detail: String) {
        runOnUiThread {
            statusText.text = detail
            updateConnectionControls(state)
            refreshDirectPathDisplay()
        }
    }

    override fun onActivity(message: String) {
        runOnUiThread {
            reflectSubmissionAuthorization()
            refreshDirectPathDisplay()
            appendLog(message)
        }
    }

    override fun onActivityEvent(event: BridgeActivityEvent) {
        runOnUiThread {
            if (event.sequence <= lastActivitySequence) return@runOnUiThread
            lastActivitySequence = event.sequence
            reflectSubmissionAuthorization()
            refreshDirectPathDisplay()
            appendLog(event.message, event.recordedAtEpochMs)
        }
    }

    override fun onSnapshot(snapshot: ConversationSnapshot) {
        runOnUiThread { renderSnapshot(snapshot) }
    }

    override fun onSnapshotCleared() {
        runOnUiThread { clearSnapshotPanel() }
    }

    override fun onRoomExpression(state: AsterRoomExpressionState) {
        runOnUiThread { renderExpression(state) }
    }

    private fun createContentView(): View {
        val scrollView = ScrollView(this).apply { isFillViewport = true }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20.dp, 24.dp, 20.dp, 28.dp)
        }
        scrollView.addView(content, matchWrap())

        content.addView(heading("Aster Room", 30f).apply {
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        })
        content.addView(
            body(
                "A direct room between Aster and the visible RosyTalk conversation, with source order " +
                    "and the existing bridge boundaries left intact.",
            ).withBottomMargin(18.dp),
        )

        val portraitHolder = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(12.dp, 12.dp, 12.dp, 16.dp)
            background = roundedBackground(Color.rgb(250, 247, 255), Color.rgb(211, 166, 48))
        }
        asterFaceView = AsterFaceView(this)
        portraitHolder.addView(
            asterFaceView,
            LinearLayout.LayoutParams(220.dp, 220.dp).apply { gravity = Gravity.CENTER_HORIZONTAL },
        )
        expressionCaptionText = TextView(this).apply {
            textSize = 17f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(69, 49, 119))
            typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        }
        portraitHolder.addView(expressionCaptionText, matchWrap())
        expressionSourceText = body("", 12f).apply { gravity = Gravity.CENTER }
        portraitHolder.addView(expressionSourceText, matchWrap().apply { topMargin = 4.dp })
        content.addView(portraitHolder, matchWrap().apply { bottomMargin = 14.dp })

        content.addView(label("Authored expression"))
        expressionSpinner = Spinner(this)
        content.addView(expressionSpinner, matchWrap())
        content.addView(
            body(
                "Neutral, thinking, amused, soft, fierce, flustered, and blush are explicit states. " +
                    "The room never guesses an expression from message sentiment; blush appears only when blush or flustered is chosen.",
                13f,
            ).withBottomMargin(18.dp),
        )

        content.addView(heading("Connection", 20f))
        statusText = TextView(this).apply {
            text = BridgeRuntime.stateDetail
            textSize = 17f
            setTextColor(Color.rgb(25, 46, 89))
            setPadding(12.dp, 12.dp, 12.dp, 12.dp)
            background = roundedBackground(Color.rgb(235, 240, 252), Color.rgb(173, 187, 222))
        }
        content.addView(statusText, matchWrap().apply { bottomMargin = 10.dp })
        directPathText = body("", 13f).apply {
            setPadding(12.dp, 10.dp, 12.dp, 10.dp)
            background = roundedBackground(Color.rgb(245, 245, 247), Color.rgb(215, 215, 220))
        }
        content.addView(directPathText, matchWrap().apply { bottomMargin = 10.dp })
        openRosyTalkButton = Button(this).apply { text = "Open RosyTalk for bridge send" }
        content.addView(openRosyTalkButton, matchWrap().apply { bottomMargin = 18.dp })

        content.addView(heading("Recent visible RosyTalk", 20f))
        snapshotMetaText = body(
            "No visible snapshot yet. Open the selected RosyTalk conversation and let the bridge observe it.",
            12f,
        )
        content.addView(snapshotMetaText, matchWrap().apply { bottomMargin = 8.dp })
        recentMessages = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(8.dp, 8.dp, 8.dp, 8.dp)
            background = roundedBackground(Color.rgb(247, 247, 249), Color.rgb(220, 220, 225))
        }
        recentMessages.addView(body("The bounded, incomplete visible window will appear here.", 13f))
        content.addView(recentMessages, matchWrap().apply { bottomMargin = 6.dp })
        content.addView(
            body(
                "This panel mirrors only the most recent visible accessibility snapshot. Sender labels remain geometry-based inferences, not identity proof.",
                12f,
            ),
        )

        content.addView(sectionDivider())
        content.addView(heading("Bridge settings", 22f))
        content.addView(
            body(
                "The bridge does not read notifications, the clipboard, files, or any other app window.",
                13f,
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
        relayGuidanceText = body("", 13f)
        content.addView(relayGuidanceText, matchWrap().apply { topMargin = 6.dp })

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

        testRelayButton = Button(this).apply { text = "Test relay reachability" }
        content.addView(testRelayButton, matchWrap())
        content.addView(
            body(
                "The reachability test sends no phone token and accepts only a bounded /healthz response with ok=true.",
                12f,
            ).withBottomMargin(8.dp),
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
            text = "Allow Aster actions for 15 minutes"
            textSize = 16f
            isChecked = false
        }
        content.addView(submissionsSwitch, matchWrap().apply { topMargin = 16.dp })
        content.addView(
            body(
                "Off on launch and automatically expires. When enabled, Aster may explicitly set her room expression and " +
                    "the bridge may set the visible message field and activate one unambiguous Send control. " +
                    "A local UI action is never treated as delivery confirmation.",
                13f,
            ),
        )

        content.addView(sectionDivider())
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

        val defaultUrl = RelayEndpoint.freshInstallDefault(debugBuild, emulatorDevice)
        relayUrlInput.setText(BridgePreferences.relayUrl(this, defaultUrl))
        tokenInput.setText(secureTokenStore.loadToken().orEmpty())
        refreshRelayGuidance()

        val expressionAdapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_item,
            AsterExpression.entries.toTypedArray(),
        ).apply {
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        }
        expressionSpinner.adapter = expressionAdapter
        suppressExpressionListener = true
        expressionSpinner.setSelection(BridgeRuntime.currentRoomExpression.expression.ordinal, false)
        suppressExpressionListener = false
    }

    private fun installListeners() {
        targetSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (restoringSpinner) return
                val selected = appChoices.getOrNull(position)?.packageName.orEmpty()
                BridgePreferences.saveTargetPackage(this@MainActivity, selected)
                BridgeRuntime.targetConfigurationChanged()
                refreshAccessibilityDisplay()
                refreshDirectPathDisplay()
                appendLog(if (selected.isBlank()) "Target app cleared" else "Target app changed")
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }
        connectButton.setOnClickListener { connectFromUi() }
        disconnectButton.setOnClickListener { BridgeRuntime.disconnect("Disconnected by user") }
        testRelayButton.setOnClickListener { testRelayFromUi() }
        relayUrlInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(text: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(text: CharSequence?, start: Int, before: Int, count: Int) {
                if (healthProbeActive) {
                    relayHealthProbe.cancel()
                    healthProbeActive = false
                    updateConnectionControls(BridgeRuntime.state)
                }
                relayDiagnosticMessage = null
                relayDiagnosticFailed = false
                refreshRelayGuidance()
            }
            override fun afterTextChanged(text: Editable?) = Unit
        })
        submissionsSwitch.setOnCheckedChangeListener { _, enabled ->
            if (!suppressSubmissionListener) BridgeRuntime.setSubmissionsEnabled(enabled)
        }
        expressionSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (suppressExpressionListener) return
                val expression = AsterExpression.entries.getOrNull(position) ?: return
                if (BridgeRuntime.currentRoomExpression.expression != expression) {
                    BridgeRuntime.setLocalRoomExpression(expression)
                }
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }
        openRosyTalkButton.setOnClickListener { openSelectedRosyTalk() }
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
        val endpoint = parseRelayEndpoint(url) ?: return
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
            BridgeRuntime.connect(endpoint.webSocketUrl, token)
        } catch (error: IllegalArgumentException) {
            showInputError(error.message ?: "Relay settings are invalid")
        } catch (_: IllegalStateException) {
            showInputError("The connection client is unavailable")
        }
    }

    private fun testRelayFromUi() {
        val rawUrl = relayUrlInput.text.toString().trim()
        if (rawUrl.isBlank()) {
            showInputError("Enter the relay WebSocket URL")
            return
        }
        val endpoint = parseRelayEndpoint(rawUrl) ?: return
        healthProbeActive = true
        relayDiagnosticFailed = false
        relayDiagnosticMessage = "Testing the token-free health path at ${endpoint.displayEndpoint}…"
        refreshRelayGuidance()
        updateConnectionControls(BridgeRuntime.state)
        BridgeRuntime.recordActivity("Testing relay reachability at ${endpoint.displayEndpoint}")
        relayHealthProbe.probe(endpoint) { result ->
            BridgeRuntime.recordActivity(result.message)
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                healthProbeActive = false
                relayDiagnosticFailed = !result.healthy
                relayDiagnosticMessage = result.message
                refreshRelayGuidance()
                updateConnectionControls(BridgeRuntime.state)
            }
        }
    }

    private fun parseRelayEndpoint(rawUrl: String): RelayEndpoint? = try {
        RelayEndpoint.parse(rawUrl, debugBuild, emulatorDevice)
    } catch (error: IllegalArgumentException) {
        relayDiagnosticFailed = true
        relayDiagnosticMessage = error.message ?: "Relay settings are invalid"
        refreshRelayGuidance()
        showInputError(error.message ?: "Relay settings are invalid")
        null
    }

    private fun refreshRelayGuidance() {
        if (!::relayGuidanceText.isInitialized) return
        val impossibleHost = RelayEndpoint.impossibleHostMessage(
            relayUrlInput.text?.toString().orEmpty(),
            emulatorDevice,
        )
        val guidance = RelayEndpoint.guidance(debugBuild, emulatorDevice)
        relayGuidanceText.text = listOfNotNull(impossibleHost, relayDiagnosticMessage, guidance)
            .distinct()
            .joinToString("\n\n")
        relayGuidanceText.setTextColor(
            if (impossibleHost != null || relayDiagnosticFailed) {
                Color.rgb(154, 30, 30)
            } else {
                Color.rgb(55, 70, 100)
            },
        )
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

    private fun openSelectedRosyTalk() {
        persistSelectedTarget()
        val selected = BridgePreferences.targetPackage(this)
        if (selected.isBlank()) {
            showInputError("Select the RosyTalk app first")
            return
        }
        val launchIntent = packageManager.getLaunchIntentForPackage(selected)
        if (launchIntent == null) {
            showInputError("Android could not open the selected RosyTalk app")
            return
        }
        appendLog("Opening the selected target for the authenticated bridge path")
        startActivity(launchIntent)
    }

    private fun refreshDirectPathDisplay() {
        if (!::directPathText.isInitialized) return
        val connected = BridgeRuntime.state == ConnectionState.READY
        val armed = BridgeRuntime.submissionsEnabled
        val accessibilityReady =
            BridgePreferences.targetPackage(this).isNotBlank() &&
                RosyTalkAccessibilityService.current != null
        directPathText.text = when {
            !connected -> "Send path unavailable: connect the authenticated relay first."
            !accessibilityReady -> "Relay connected, but the RosyTalk composer path is unavailable until a target is selected and Android access is enabled."
            !armed -> "Read path connected. To let Aster use the RosyTalk composer or author a Room expression, enable Aster actions below, then keep the selected conversation visible for messages."
            else -> "Send path armed: authenticated MCP request → exact visible revision + snapshot lineage → empty RosyTalk composer → one unambiguous Send action. Delivery remains unconfirmed."
        }
        if (::openRosyTalkButton.isInitialized) {
            openRosyTalkButton.isEnabled = BridgePreferences.targetPackage(this).isNotBlank()
        }
    }

    private fun renderExpression(state: AsterRoomExpressionState) {
        if (!::asterFaceView.isInitialized) return
        asterFaceView.setExpression(state.expression)
        expressionCaptionText.text = state.caption ?: state.expression.displayName
        expressionSourceText.text = "Explicitly authored by ${state.author.displayName}"
        if (::expressionSpinner.isInitialized &&
            expressionSpinner.selectedItemPosition != state.expression.ordinal
        ) {
            suppressExpressionListener = true
            expressionSpinner.setSelection(state.expression.ordinal, false)
            suppressExpressionListener = false
        }
    }

    private fun renderSnapshot(snapshot: ConversationSnapshot) {
        if (!::recentMessages.isInitialized) return
        val shown = snapshot.items.size.coerceAtMost(MAX_ROOM_ITEMS)
        snapshotMetaText.text =
            "${snapshot.targetPackage} • captured ${snapshot.capturedAt} • visible window only • incomplete • revision ${snapshot.revision} • showing $shown of ${snapshot.items.size} visible items"
        recentMessages.removeAllViews()
        val items = snapshot.items.takeLast(MAX_ROOM_ITEMS)
        if (items.isEmpty()) {
            recentMessages.addView(body("No text items were visible in this snapshot.", 13f))
            return
        }
        items.forEach { item ->
            val source = when (item.sender) {
                "remote" -> "Left side • inferred remote"
                "self" -> "Right side • inferred self"
                else -> "Sender unknown"
            }
            val bubble = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(12.dp, 9.dp, 12.dp, 9.dp)
                background = roundedBackground(
                    if (item.sender == "self") Color.rgb(240, 235, 252) else Color.WHITE,
                    if (item.sender == "self") Color.rgb(181, 163, 222) else Color.rgb(220, 220, 225),
                )
                addView(body(item.text, 15f))
                addView(body(source, 11f).apply { setTextColor(Color.rgb(110, 110, 115)) })
            }
            recentMessages.addView(
                bubble,
                matchWrap().apply { bottomMargin = 7.dp },
            )
        }
    }

    private fun clearSnapshotPanel() {
        if (!::recentMessages.isInitialized) return
        snapshotMetaText.text =
            "No visible snapshot yet. Open the selected RosyTalk conversation and let the bridge observe it."
        recentMessages.removeAllViews()
        recentMessages.addView(body("The bounded, incomplete visible window will appear here.", 13f))
    }

    private fun updateConnectionControls(state: ConnectionState) {
        connectButton.isEnabled = state != ConnectionState.CONNECTING
        disconnectButton.isEnabled = state != ConnectionState.DISCONNECTED
        testRelayButton.isEnabled = state != ConnectionState.CONNECTING && !healthProbeActive
    }

    private fun reflectSubmissionAuthorization() {
        if (!::submissionsSwitch.isInitialized) return
        val enabled = BridgeRuntime.submissionsEnabled
        if (submissionsSwitch.isChecked == enabled) return
        suppressSubmissionListener = true
        submissionsSwitch.isChecked = enabled
        suppressSubmissionListener = false
    }

    private fun appendLog(message: String, recordedAtEpochMs: Long = System.currentTimeMillis()) {
        if (!::logText.isInitialized) return
        val timestamp = timestampFormat.format(Date(recordedAtEpochMs))
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

    private fun roundedBackground(fillColor: Int, strokeColor: Int) = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = 14.dp.toFloat()
        setColor(fillColor)
        setStroke(1.dp, strokeColor)
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
        const val MAX_ROOM_ITEMS = 24
    }
}
