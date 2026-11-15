package pl.halorush.controller

import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothManager
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.graphics.drawable.StateListDrawable
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.InputType
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.TextWatcher
import android.text.style.AbsoluteSizeSpan
import android.text.style.ForegroundColorSpan
import android.text.style.TypefaceSpan
import android.util.Log
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.*
import android.window.OnBackInvokedDispatcher
import com.neurotec.brainaccess.core.BrainAccessClient
import com.neurotec.brainaccess.core.DeviceSession
import com.neurotec.brainaccess.transport.BlePermissions
import com.neurotec.brainaccess.transport.NordicTransport
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.drop

/**
 * Two moods: setup is light and calm (the phone is in your hand for half a minute), play is dark (the phone lies
 * on the table while you play with your head and eyes). On the play screen the head map shows at a glance which
 * electrode lost contact; a short vibration confirms every move the server sent to the game.
 */
class MainActivity : Activity() {
    private enum class Screen { SERVER, DEVICE, CONNECTING, STATUS, MANUAL }
    private data class DeviceChoice(val name: String, val id: String, val open: suspend () -> DeviceSession)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var client: BrainAccessClient? = null
    private var haloScope: CoroutineScope? = null
    private lateinit var root: LinearLayout
    private var screen = Screen.SERVER
    private var visible = false
    private var scanJob: Job? = null
    private var runJob: Job? = null
    private var scanning = false
    private var running = false
    private var stopping = false
    // Invalidates queued callbacks after cancel/back, including callbacks already on the UI queue.
    private var scanGeneration = 0
    private var sessionGeneration = 0
    private val choices = linkedMapOf<String, DeviceChoice>()
    private var selected: DeviceChoice? = null
    private var serverUrl = ""
    private var bearerToken = ""
    private var playerNumber = 1
    private var manualMode = false
    private var lastDevice = ""
    private var manualController: ManualController? = null
    private var manualFeedback: TextView? = null
    private var pressCount = 0L
    private var lastManualFeedback = "Ready to play"
    private var modeField: RadioGroup? = null
    private var phase: ConnectionPhase? = null
    private var connectionMessage = ""
    private var connectionError: String? = null
    private var deviceMessage = "Turn on the headband and keep it close to the phone."
    private var latestStats: StreamStats? = null
    private var lastDirection: String? = null          // last move from the server: left / right / up / down

    private var endpointField: EditText? = null
    private var tokenField: EditText? = null
    private var playerField: RadioGroup? = null
    private var formError: TextView? = null
    private var deviceList: LinearLayout? = null
    private var deviceStatus: TextView? = null
    private var searchButton: Button? = null
    private var metrics: TextView? = null
    private var headMap: HeadMapView? = null
    private var contactMessage: TextView? = null
    private var moveBadge: TextView? = null
    private var moveWord: TextView? = null

    // jasne ekrany konfiguracji
    private val mist = Color.rgb(0xf2, 0xf3, 0xf8)
    private val paper = Color.WHITE
    private val line = Color.rgb(0xdc, 0xdf, 0xec)
    private val ink = Color.rgb(0x15, 0x19, 0x36)
    private val inkSoft = Color.rgb(0x5e, 0x63, 0x85)
    // ciemne ekrany gry
    private val night = Color.rgb(0x0f, 0x12, 0x26)
    private val nightSurface = Color.rgb(0x1a, 0x1e, 0x3a)
    private val nightLine = Color.rgb(0x2c, 0x31, 0x57)
    private val nightInk = Color.rgb(0xf1, 0xf2, 0xfa)
    private val nightSoft = Color.rgb(0x9d, 0xa2, 0xc9)
    // akcenty
    private val wave = Color.rgb(0x5b, 0x4c, 0xf5)
    private val wavePressed = Color.rgb(0x46, 0x36, 0xe0)
    private val waveTint = Color.rgb(0xec, 0xea, 0xff)
    private val contactOk = Color.rgb(0x22, 0xc5, 0x8b)
    private val contactOkInk = Color.rgb(0x0e, 0x8a, 0x5f)      // green, readable on a light background
    private val spark = Color.rgb(0xff, 0x5f, 0x57)
    private val sparkInk = Color.rgb(0xc0, 0x35, 0x2c)          // red, readable on a light background
    private val sparkTint = Color.rgb(0xff, 0xec, 0xeb)
    private val headFace: Typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD)
    private val mediumFace: Typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)

    private val dark get() = screen == Screen.STATUS || screen == Screen.MANUAL

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("controller", MODE_PRIVATE)
        serverUrl = savedInstanceState?.getString("endpoint") ?: prefs.getString("endpoint", "").orEmpty()
        playerNumber = (savedInstanceState?.getInt("player") ?: prefs.getInt("player", 1)).coerceIn(1, 2)
        manualMode = savedInstanceState?.getBoolean("manual_mode") ?: prefs.getBoolean("manual_mode", false)
        lastDevice = prefs.getString("last_device", "").orEmpty()
        show(Screen.SERVER)
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT) { back() }
        }
    }

    private fun show(next: Screen) {
        screen = next
        endpointField = null; tokenField = null; playerField = null; formError = null
        deviceList = null; deviceStatus = null; searchButton = null; modeField = null; manualFeedback = null
        metrics = null; headMap = null; contactMessage = null; moveBadge = null; moveWord = null
        if (next == Screen.MANUAL) {
            manualScreen()
            setControllerFullscreen(true)
            return
        }
        val bg = if (dark) night else mist
        root = column().apply { setPadding(dp(22), dp(18), dp(22), dp(28)) }
        val scroll = ScrollView(this).apply { addView(root); isFillViewport = true; setBackgroundColor(bg) }
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or WindowInsets.Type.ime())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        setContentView(scroll)
        // PhoneWindow's insets controller requires an existing decor view (Android 11+).
        setControllerFullscreen(false)
        if (!dark) progress(next)
        when (next) {
            Screen.SERVER -> serverScreen()
            Screen.DEVICE -> deviceScreen()
            Screen.CONNECTING -> connectingScreen()
            Screen.STATUS -> statusScreen()
            Screen.MANUAL -> manualScreen()
        }
    }

    /** Wordmark and where this screen is in the setup (a real sequence, so numbered steps). */
    private fun progress(current: Screen) {
        val top = row().apply { gravity = Gravity.CENTER_VERTICAL }
        top.addView(TextView(this).apply { text = "halo"; textSize = 22f; typeface = headFace; setTextColor(wave); letterSpacing = -0.02f })
        val labels = if (manualMode) listOf("Server", "Connecting", "Game") else listOf("Server", "Headband", "Connecting", "Game")
        val position = if (manualMode) when (current) { Screen.SERVER -> 0; Screen.CONNECTING -> 1; else -> 2 } else current.ordinal
        top.addView(View(this), LinearLayout.LayoutParams(0, 1, 1f))
        top.addView(TextView(this).apply {
            text = "Step ${position + 1} of ${labels.size}: ${labels[position].lowercase()}"
            textSize = 13f; setTextColor(inkSoft)
        })
        root.addView(top)
        space(root, 10)
        val steps = row()
        labels.indices.forEach { index ->
            steps.addView(View(this).apply { background = rounded(if (index <= position) wave else line, 999) },
                LinearLayout.LayoutParams(0, dp(5), 1f).apply { marginEnd = if (index < labels.size - 1) dp(5) else 0 })
        }
        root.addView(steps)
        space(root, 26)
    }

    private fun title(value: String, description: String? = null, color: Int = ink, soft: Int = inkSoft) {
        text(root, value, 34, color).apply { typeface = headFace; letterSpacing = -0.015f; setLineSpacing(0f, 0.92f) }
        if (description != null) text(root, description, 16, soft).setLineSpacing(0f, 1.15f)
        space(root, 18)
    }

    private fun serverScreen() {
        title("Connect to the game", "Enter the address of the computer running the game server.")
        label(root, "Computer address")
        endpointField = field(root, "e.g. 172.20.10.2", serverUrl,
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        val resolved = text(root, "", 13, inkSoft)
        endpointField?.apply {
            fun preview() {
                val typed = text.toString()
                val url = ServerAddress.normalize(typed)
                resolved.text = when {
                    typed.isBlank() -> "The IP is enough. The server shows it when it starts."
                    url == null -> "That is not an address. Enter the computer's IP, e.g. 192.168.1.20."
                    else -> "✓ Will connect to $url"
                }
                resolved.setTextColor(when { typed.isBlank() -> inkSoft; url == null -> sparkInk; else -> contactOkInk })
            }
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) = preview()
            })
            preview()
        }

        label(root, "Which player are you?")
        playerField = RadioGroup(this).apply {
            orientation = RadioGroup.HORIZONTAL
            for (number in 1..2) addView(playerTile(number), RadioGroup.LayoutParams(0, dp(104), 1f).apply {
                if (number == 1) marginEnd = dp(10)
            })
            check(playerNumber)
            root.addView(this, LinearLayout.LayoutParams(-1, -2))
        }

        label(root, "How do you control?")
        modeField = RadioGroup(this).apply {
            orientation = RadioGroup.VERTICAL
            addView(option(R.id.mode_halo, ModeIcon.Kind.HEADBAND, "HALO headband", "With head moves and blinks."),
                RadioGroup.LayoutParams(-1, -2).apply { bottomMargin = dp(10) })
            addView(option(R.id.mode_manual, ModeIcon.Kind.PAD, "On-screen pad", "With buttons on the phone, no headband."),
                RadioGroup.LayoutParams(-1, -2))
            check(if (manualMode) R.id.mode_manual else R.id.mode_halo)
            root.addView(this)
        }

        space(root, 6)
        val tokenLink = textButton(root, "Server needs a token?")
        tokenField = field(root, "Access token", bearerToken,
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD).apply { isSaveEnabled = false }
        if (bearerToken.isBlank()) tokenField?.visibility = View.GONE else tokenLink.visibility = View.GONE
        tokenLink.setOnClickListener {
            tokenLink.visibility = View.GONE
            tokenField?.apply { visibility = View.VISIBLE; requestFocus() }
        }
        formError = text(root, "", 14, sparkInk).apply {
            visibility = View.GONE; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        space(root, 14)
        button(root, "Next") { continueToDevice() }
        space(root, 6)
        text(root, "The phone and the computer must be on the same Wi-Fi network, or the phone on the computer's hotspot.", 13, inkSoft)
            .gravity = Gravity.CENTER_HORIZONTAL
    }

    private fun captureForm() {
        endpointField?.let { serverUrl = it.text.toString().trim() }
        tokenField?.let { bearerToken = it.text.toString() }
        playerField?.let { playerNumber = it.checkedRadioButtonId }
        modeField?.let { manualMode = it.checkedRadioButtonId == R.id.mode_manual }
    }

    private fun continueToDevice() {
        captureForm()
        val url = ServerAddress.normalize(serverUrl)
        if (url == null || bearerToken.contains('\n') || bearerToken.contains('\r')) {
            formError?.apply {
                text = if (url == null) "Enter the computer's address: just the IP, e.g. 192.168.1.20, or a full ws:// address."
                    else "The token cannot contain line breaks."
                visibility = View.VISIBLE
            }
            return
        }
        serverUrl = url
        bearerToken = bearerToken.trim()
        getSharedPreferences("controller", MODE_PRIVATE).edit().putString("endpoint", serverUrl)
            .putInt("player", playerNumber).putBoolean("manual_mode", manualMode).apply()
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(root.windowToken, 0)
        deviceMessage = "Turn on the headband and keep it close to the phone."
        if (manualMode) connectManual() else show(Screen.DEVICE)
    }

    private fun deviceScreen() {
        title("Find the headband", "Turn on HALO and disconnect it from the computer. The headband connects to only one device at a time.")
        text(root, "Player $playerNumber, server ${ServerAddress.short(serverUrl)}", 14, inkSoft)
        space(root, 8)
        deviceStatus = text(root, deviceMessage, 15, ink).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        space(root, 4)
        searchButton = button(root, if (scanning) "Searching for headbands…" else "Search for HALO") { ensurePermissions() }
            .apply { isEnabled = !scanning }
        if (scanning) root.addView(ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = true; indeterminateTintList = ColorStateList.valueOf(wave)
        }, LinearLayout.LayoutParams(-1, dp(6)).apply { topMargin = dp(4) })
        space(root, 12)
        deviceList = column().also { root.addView(it) }
        renderDevices()
        space(root, 12)
        button(root, "Change server", false) { cancelScan(); show(Screen.SERVER) }
        space(root, 4)
        text(root, "Headband not on the list? Check that it is lit and not connected to the BrainGestures app on the computer. On Android 11 and older, also turn on location.", 13, inkSoft)
    }

    private fun renderDevices() {
        val list = deviceList ?: return
        list.removeAllViews()
        if (choices.isEmpty()) {
            val empty = column().apply {
                background = GradientDrawable().apply {
                    setColor(Color.TRANSPARENT); cornerRadius = dp(18).toFloat()
                    setStroke(dp(2), line, dp(7).toFloat(), dp(6).toFloat())
                }
                setPadding(dp(20), dp(18), dp(20), dp(18))
            }
            text(empty, if (scanning) "Searching nearby…" else "Headbands found will appear here", 17, ink).typeface = mediumFace
            text(empty, "Tap a name to connect.", 14, inkSoft)
            list.addView(empty, LinearLayout.LayoutParams(-1, -2))
        } else choices.values.sortedByDescending { it.name == lastDevice }.forEach { device ->
            val recent = device.name == lastDevice
            val card = row().apply {
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(18), dp(14), dp(14), dp(14)); minimumHeight = dp(72)
                background = RippleDrawable(ColorStateList.valueOf(waveTint),
                    roundedStroke(paper, if (recent) wave else line, if (recent) 2 else 1, 18), rounded(Color.WHITE, 18))
                isClickable = true; isFocusable = true
                contentDescription = "Connect to ${device.name}" + if (recent) ", used last time" else ""
                setOnClickListener { cancelScan(); selected = device; connect() }
            }
            val texts = column()
            texts.addView(TextView(this).apply { text = device.name; textSize = 18f; typeface = mediumFace; setTextColor(ink) })
            texts.addView(TextView(this).apply { text = device.id; textSize = 13f; setTextColor(inkSoft) })
            card.addView(texts, LinearLayout.LayoutParams(0, -2, 1f))
            if (recent) card.addView(TextView(this).apply {
                text = "ostatnio"; textSize = 12f; typeface = mediumFace; setTextColor(wave)
                background = rounded(waveTint, 999); setPadding(dp(10), dp(4), dp(10), dp(4))
            }, LinearLayout.LayoutParams(-2, -2).apply { marginEnd = dp(8) })
            card.addView(TextView(this).apply { text = "›"; textSize = 26f; setTextColor(inkSoft) })
            list.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(10) })
        }
    }

    private fun ensurePermissions() {
        if (screen != Screen.DEVICE || stopping || running) return
        // Even reading the adapter or constructing the SDK must happen after permission.
        val missing = BlePermissions.required.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) startHaloScan() else requestPermissions(missing.toTypedArray(), 1)
    }

    @SuppressLint("MissingPermission") // All SDK permissions are checked above, including after a grant.
    private fun startHaloScan() {
        try {
            val adapter = getSystemService(BluetoothManager::class.java)?.adapter
            if (adapter == null || !packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)) {
                deviceMessage = "This phone does not provide the Bluetooth LE that HALO needs."
                show(Screen.DEVICE); return
            }
            if (!adapter.isEnabled) {
                deviceMessage = "Turn on Bluetooth in the phone settings first."
                show(Screen.DEVICE); return
            }
            if (client == null) initializeHalo()
            scan()
        } catch (e: Exception) {
            haloFailure(e)
        } catch (e: LinkageError) {
            haloFailure(e)
        }
    }

    private fun initializeHalo() {
        val job = SupervisorJob()
        val handler = CoroutineExceptionHandler { _, error ->
            runOnUiThread {
                if (haloScope?.coroutineContext?.get(Job) === job) haloFailure(error)
            }
        }
        // Own the SDK's background jobs too; an internal flow failure must not crash the process.
        val sdkScope = CoroutineScope(job + Dispatchers.Main + handler)
        haloScope = sdkScope
        val created = BrainAccessClient(NordicTransport(applicationContext), scope = sdkScope)
        client = created
        sdkScope.launch {
            // The StateFlow's initial value isn't a completed adapter check.
            created.bluetoothState.drop(1).collect { on ->
                if (!on && !manualMode) {
                    if (running) endSession(Screen.DEVICE, "Bluetooth is off. Turn it on and choose HALO again.")
                    else if (screen == Screen.DEVICE) {
                        cancelScan()
                        deviceMessage = "Turn on Bluetooth to search for HALO."
                        show(Screen.DEVICE)
                    }
                } else if (on && screen == Screen.DEVICE && !running && !stopping && !scanning) {
                    deviceMessage = "Bluetooth is on. You can search for the headband."
                    show(Screen.DEVICE)
                }
            }
        }
    }

    private fun haloFailure(error: Throwable) {
        Log.e("HaloController", "HALO initialization / Bluetooth monitor failed", error)
        haloScope?.cancel(); haloScope = null; client = null
        selected = null
        val message = "Could not start HALO (${error.javaClass.simpleName}): ${error.message ?: "Bluetooth SDK error"}"
        if (!manualMode && screen != Screen.SERVER) endSession(Screen.DEVICE, message)
        else deviceMessage = message
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 1 || !visible || screen != Screen.DEVICE) return
        if (grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) ensurePermissions()
        else {
            deviceMessage = "Allow Bluetooth access to search for the headband. You can try again."
            show(Screen.DEVICE)
        }
    }

    private fun scan() {
        val scanClient = client ?: return
        if (scanning || running || stopping) return
        cancelScan()
        val generation = scanGeneration
        choices.clear(); scanning = true
        deviceMessage = "Searching for up to 15 seconds. You can pick a headband as soon as it appears."
        show(Screen.DEVICE)
        scanJob = scope.launch {
            try {
                withTimeout(15_000) {
                    scanClient.scan().collect { device ->
                        if (generation == scanGeneration && screen == Screen.DEVICE &&
                            device.model.toString().contains("HALO", ignoreCase = true)) {
                            val key = device.id.toString()
                            if (!choices.containsKey(key)) {
                                choices[key] = DeviceChoice(device.name, key) { scanClient.connect(device).getOrThrow() }
                                renderDevices()
                            }
                        }
                    }
                }
            } catch (_: TimeoutCancellationException) {
                deviceMessage = if (choices.isEmpty()) "No HALO found. Check the headband and search again." else "Choose a headband from the list."
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { deviceMessage = "Could not search for headbands: ${e.message}"
            } finally {
                if (generation == scanGeneration) {
                    scanning = false
                    if (screen == Screen.DEVICE) show(Screen.DEVICE)
                }
            }
        }
    }

    private fun cancelScan() {
        scanGeneration++
        scanJob?.cancel(); scanJob = null; scanning = false
    }

    private fun connectingScreen() {
        val error = connectionError
        title(when {
            stopping -> "Ending session"
            error != null -> "Could not connect"
            phase == ConnectionPhase.RETRYING -> "Rejoining the game"
            else -> "Connecting"
        }, if (manualMode) "On-screen pad, player $playerNumber" else "${selected?.name ?: "HALO"}, player $playerNumber")
        if (error != null) {
            text(root, error, 15, sparkInk).apply {
                background = rounded(sparkTint, 14); setPadding(dp(16), dp(14), dp(16), dp(14))
                accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            }
        } else {
            val step = if (stopping) -1 else if (manualMode) { if (phase == ConnectionPhase.REGISTERING) 1 else 0 } else when (phase) {
                null -> 0
                ConnectionPhase.SERVER, ConnectionPhase.RETRYING -> 1
                else -> 2
            }
            val steps = if (manualMode) listOf("Game server", "Pad mode") else listOf("Headband over Bluetooth", "Game server", "Player slot")
            if (step >= 0) steps.forEachIndexed { index, label -> timelineRow(label, index < step, index == step) }
            space(root, 6)
            text(root, connectionMessage, 14, inkSoft).accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        space(root, 6)
        text(root, "Server ${ServerAddress.short(serverUrl)}", 14, inkSoft)
        space(root, 14)
        if (error != null) {
            button(root, "Try again") { if (manualMode) connectManual() else connect() }
            if (!manualMode) button(root, "Choose another headband", false) { choices.clear(); show(Screen.DEVICE) }
            button(root, "Change server", false) { show(Screen.SERVER) }
        } else {
            button(root, if (stopping) "Disconnecting…" else "Cancel", false) {
                endSession(setupScreen(), "Connection cancelled. Choose a headband or search again.")
            }.isEnabled = !stopping
        }
    }

    /** One step of connecting: done (green tick), now (spinner), later (empty ring). */
    private fun timelineRow(label: String, done: Boolean, now: Boolean) {
        val r = row().apply { gravity = Gravity.CENTER_VERTICAL; minimumHeight = dp(48) }
        val mark: View = if (now) ProgressBar(this).apply {
                indeterminateTintList = ColorStateList.valueOf(wave)
                // the ring marks the current step even when the spinner is not moving (animations off)
                background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setStroke(dp(2), waveTint) }
            }
            else TextView(this).apply {
                text = if (done) "✓" else ""; gravity = Gravity.CENTER; textSize = 14f; typeface = mediumFace
                setTextColor(Color.WHITE)
                background = if (done) oval(contactOk) else GradientDrawable().apply { shape = GradientDrawable.OVAL; setStroke(dp(2), line) }
            }
        r.addView(mark, LinearLayout.LayoutParams(dp(26), dp(26)).apply { marginEnd = dp(14) })
        r.addView(TextView(this).apply {
            text = label; textSize = 17f; setTextColor(if (done || now) ink else inkSoft)
            typeface = if (now) mediumFace else Typeface.DEFAULT
        })
        root.addView(r)
    }

    /** During play: is it sending, which electrode lost contact (and where on the head), the last move. */
    private fun statusScreen() {
        val top = row().apply { gravity = Gravity.CENTER_VERTICAL }
        val who = column()
        who.addView(TextView(this).apply { text = "Player $playerNumber"; textSize = 34f; typeface = headFace; setTextColor(nightInk) })
        who.addView(TextView(this).apply { text = selected?.name ?: "HALO"; textSize = 15f; setTextColor(nightSoft) })
        top.addView(who, LinearLayout.LayoutParams(0, -2, 1f))
        top.addView(row().apply {
            gravity = Gravity.CENTER_VERTICAL
            background = rounded(Color.argb(0x26, 0x22, 0xc5, 0x8b), 999); setPadding(dp(12), dp(7), dp(14), dp(7))
            addView(View(context).apply { background = oval(contactOk) }, LinearLayout.LayoutParams(dp(9), dp(9)).apply { marginEnd = dp(7) })
            addView(TextView(context).apply { text = "Streaming"; textSize = 14f; typeface = mediumFace; setTextColor(contactOk) })
            contentDescription = "The phone is streaming data to the server"
        })
        root.addView(top)
        space(root, 10)
        headMap = HeadMapView(this).also { root.addView(it, LinearLayout.LayoutParams(dp(260), dp(260)).apply { gravity = Gravity.CENTER_HORIZONTAL }) }
        contactMessage = text(root, HeadMapView.describe(null), 16, nightSoft).apply {
            gravity = Gravity.CENTER_HORIZONTAL; typeface = mediumFace
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        space(root, 18)
        val move = row().apply {
            gravity = Gravity.CENTER_VERTICAL
            background = rounded(nightSurface, 22); setPadding(dp(16), dp(14), dp(16), dp(14))
        }
        moveBadge = TextView(this).apply {
            gravity = Gravity.CENTER; textSize = 36f; typeface = headFace; setTextColor(Color.WHITE)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }
        move.addView(moveBadge, LinearLayout.LayoutParams(dp(64), dp(64)).apply { marginEnd = dp(16) })
        val moveText = column()
        moveText.addView(TextView(this).apply { text = "Last move in the game"; textSize = 14f; setTextColor(nightSoft) })
        moveWord = TextView(this).apply {
            textSize = 24f; typeface = headFace; setTextColor(nightInk)
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        moveText.addView(moveWord)
        move.addView(moveText, LinearLayout.LayoutParams(0, -2, 1f))
        root.addView(move, LinearLayout.LayoutParams(-1, -2))
        showMove(animate = false)
        space(root, 12)
        metrics = text(root, "Waiting for the first samples…", 14, nightSoft).apply { gravity = Gravity.CENTER_HORIZONTAL }
        latestStats?.let { renderStats(it) }
        space(root, 18)
        button(root, "End session", false) { endSession(Screen.DEVICE, "Session ended. You can connect HALO again.") }
        textButton(root, "Change server").apply { gravity = Gravity.CENTER; setOnClickListener { endSession(Screen.SERVER) } }
        text(root, "The phone can lie nearby. Do not close the app or lock the screen, or streaming will stop.", 13, nightSoft)
            .gravity = Gravity.CENTER_HORIZONTAL
    }

    /** Last move from the server: an arrow in a coloured badge and the word; a pop and a tick when it changes. */
    private fun showMove(animate: Boolean) {
        val badge = moveBadge ?: return
        val d = lastDirection
        badge.text = when (d) { "left" -> "←"; "right" -> "→"; "up" -> "↑"; "down" -> "↓"; else -> "·" }
        badge.background = oval(if (d == null) nightLine else wave)
        moveWord?.text = when (d) { "left" -> "Left"; "right" -> "Right"; "up" -> "Up"; "down" -> "Down"; else -> "None yet" }
        if (animate) {
            // the player looks at the game, not at the phone: the tick says the move was recognised
            badge.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
            badge.animate().cancel()
            badge.scaleX = 1.18f; badge.scaleY = 1.18f
            badge.animate().scaleX(1f).scaleY(1f).setDuration(180).start()
        }
    }

    private fun manualScreen() {
        // This screen intentionally has no wizard header, explanatory cards or scrolling.
        root = column().apply {
            setPadding(dp(14), dp(10), dp(14), dp(10))
            setBackgroundColor(night)
        }
        val shell = FrameLayout(this).apply { setBackgroundColor(night); addView(root, FrameLayout.LayoutParams(-1, -1)) }
        shell.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val cutout = insets.getInsets(WindowInsets.Type.displayCutout())
                view.setPadding(cutout.left, cutout.top, cutout.right, cutout.bottom)
            } else if (Build.VERSION.SDK_INT >= 28) {
                val cutout = insets.displayCutout
                view.setPadding(cutout?.safeInsetLeft ?: 0, cutout?.safeInsetTop ?: 0,
                    cutout?.safeInsetRight ?: 0, cutout?.safeInsetBottom ?: 0)
            }
            insets
        }
        setContentView(shell)
        val toolbar = row().apply { gravity = Gravity.CENTER_VERTICAL }
        root.addView(toolbar, LinearLayout.LayoutParams(-1, dp(52)))
        val players = row().apply {
            background = rounded(nightSurface, 999)
            setPadding(dp(4), dp(4), dp(4), dp(4))
        }
        toolbar.addView(players, LinearLayout.LayoutParams(-2, dp(52)))
        for (number in 1..2) {
            Button(this).apply {
                text = "Player $number"; textSize = 14f; isAllCaps = false; typeface = mediumFace
                stateListAnimator = null
                setTextColor(if (number == playerNumber) Color.WHITE else nightSoft)
                backgroundTintList = null
                background = rounded(if (number == playerNumber) wave else Color.TRANSPARENT, 999)
                minWidth = 0; minimumWidth = 0; minHeight = 0; minimumHeight = 0; setPadding(dp(14), 0, dp(14), 0)
                isEnabled = number != playerNumber
                contentDescription = if (number == playerNumber) "Player $number, selected" else "Switch to player $number"
                setOnClickListener { switchManualPlayer(number) }
                players.addView(this, LinearLayout.LayoutParams(-2, dp(44)))
            }
        }
        val online = row().apply { gravity = Gravity.CENTER; contentDescription = "Connected to the server" }
        online.addView(View(this).apply { background = oval(contactOk) }, LinearLayout.LayoutParams(dp(9), dp(9)).apply { marginEnd = dp(7) })
        online.addView(TextView(this).apply { text = "Connected"; textSize = 13f; typeface = mediumFace; setTextColor(contactOk) })
        toolbar.addView(online, LinearLayout.LayoutParams(0, -1, 1f))
        Button(this).apply {
            text = "✕"; textSize = 18f; setTextColor(nightInk)
            contentDescription = "End / change mode"
            minWidth = 0; minimumWidth = 0; minHeight = 0; minimumHeight = 0; setPadding(0, 0, 0, 0)
            stateListAnimator = null; backgroundTintList = null
            background = pressable(oval(nightSurface), oval(nightLine))
            setOnClickListener { endSession(Screen.SERVER) }
            toolbar.addView(this, LinearLayout.LayoutParams(dp(48), dp(48)))
        }
        space(root, 10)
        root.addView(RetroPadView(this) { key ->
            if (manualController?.press(key) == true) {
                pressCount++
                lastManualFeedback = "Sent ${key.uppercase()} as player $playerNumber ($pressCount)"
            } else lastManualFeedback = "Not connected, the button was not sent"
            manualFeedback?.text = lastManualFeedback
        }, LinearLayout.LayoutParams(-1, 0, 1f))
        manualFeedback = TextView(this).apply {
            text = lastManualFeedback; textSize = 13f
            setTextColor(nightSoft); gravity = Gravity.CENTER; maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            root.addView(this, LinearLayout.LayoutParams(-1, dp(30)))
        }
    }

    @Suppress("DEPRECATION")
    private fun setControllerFullscreen(enabled: Boolean) {
        // light screens: dark status/navigation icons; play screens (dark): light icons
        window.statusBarColor = if (dark) night else mist
        window.navigationBarColor = if (dark) night else mist
        if (Build.VERSION.SDK_INT >= 30) {
            window.insetsController?.apply {
                val lightBars = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
                setSystemBarsAppearance(if (dark) 0 else lightBars, lightBars)
                if (enabled) {
                    systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                    hide(WindowInsets.Type.systemBars())
                } else show(WindowInsets.Type.systemBars())
            }
        } else {
            window.decorView.systemUiVisibility = if (enabled) {
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
            } else if (dark) View.SYSTEM_UI_FLAG_VISIBLE else {
                View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or
                    if (Build.VERSION.SDK_INT >= 26) View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR else 0
            }
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && screen == Screen.MANUAL) setControllerFullscreen(true)
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        // Rotation/resizing changes only the layout. The socket, player and seq stay alive.
        captureForm()
        super.onConfigurationChanged(newConfig)
        show(screen)
    }

    private fun switchManualPlayer(number: Int) {
        if (number == playerNumber || stopping) return
        endSession(Screen.SERVER, after = {
            playerNumber = number
            getSharedPreferences("controller", MODE_PRIVATE).edit().putInt("player", number).apply()
            if (visible) connectManual() else show(Screen.SERVER)
        })
    }

    private fun connectManual() {
        if (running || stopping || runJob?.isCompleted == false) return
        cancelScan()
        running = true
        val generation = ++sessionGeneration
        connectionError = null; phase = ConnectionPhase.SERVER; pressCount = 0
        connectionMessage = "Connecting the pad to the server…"
        show(Screen.CONNECTING)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val controller = ManualController { update -> sessionUi(generation) {
            phase = update.phase; connectionMessage = update.message
            if (phase == ConnectionPhase.STREAMING) { pressCount = 0; lastManualFeedback = "Ready to play"; show(Screen.MANUAL) }
            else show(Screen.CONNECTING)
        } }
        manualController = controller
        runJob = scope.launch {
            var failure: String? = null
            try {
                withContext(Dispatchers.Default) { controller.run(serverUrl, bearerToken, playerNumber) }
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { failure = e.message ?: "Could not connect the controller."
            } finally {
                controller.release(); manualController = null; running = false
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                if (generation == sessionGeneration && failure != null) {
                    connectionError = failure; show(Screen.CONNECTING)
                }
            }
        }
    }

    private fun setupScreen() = if (manualMode) Screen.SERVER else Screen.DEVICE

    private fun connect() {
        val device = selected ?: return
        val sessionClient = client ?: return
        if (running || stopping || runJob?.isCompleted == false) return
        cancelScan()
        running = true
        lastDevice = device.name
        getSharedPreferences("controller", MODE_PRIVATE).edit().putString("last_device", device.name).apply()
        val generation = ++sessionGeneration
        connectionError = null; phase = null; latestStats = null; lastDirection = null
        connectionMessage = "Connecting to the headband over Bluetooth…"
        show(Screen.CONNECTING)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val controller = Controller(
            { update -> sessionUi(generation) {
                phase = update.phase; connectionMessage = update.message
                if (phase == ConnectionPhase.STREAMING) show(Screen.STATUS)
                else { latestStats = null; lastDirection = null; show(Screen.CONNECTING) }
            } },
            { value -> sessionUi(generation) { latestStats = value; if (screen == Screen.STATUS) renderStats(value) } },
            { direction -> sessionUi(generation) {
                lastDirection = direction
                showMove(animate = true)
            } },
        )
        runJob = scope.launch {
            var failure: String? = null
            try {
                val session = withTimeout(20_000) { device.open() }
                withContext(Dispatchers.Default) { controller.run(session, serverUrl, bearerToken, playerNumber) }
            } catch (_: TimeoutCancellationException) { failure = "HALO did not respond in time. Check the headband and try again."
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { failure = e.message ?: "A connection error occurred. Try again."
            } finally {
                // A BLE teardown failure must not strand the wizard on the disconnecting screen.
                withContext(NonCancellable) {
                    withTimeoutOrNull(5_000) { runCatching { sessionClient.disconnectAll() } }
                }
                controller.release()
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                running = false
                if (generation == sessionGeneration && failure != null) {
                    connectionError = failure
                    show(Screen.CONNECTING)
                }
            }
        }
    }

    private fun sessionUi(generation: Int, action: () -> Unit) {
        runOnUiThread { if (generation == sessionGeneration && running && visible && !stopping) action() }
    }

    private fun endSession(target: Screen, message: String = "Choose a headband to start a new session.", after: (() -> Unit)? = null) {
        if (stopping) return
        cancelScan(); sessionGeneration++
        deviceMessage = message
        choices.clear()
        connectionError = null
        val job = runJob
        if (job != null && !job.isCompleted) {
            stopping = true
            connectionMessage = if (manualMode) "Disconnecting the pad…" else "Stopping the stream and disconnecting HALO…"
            show(Screen.CONNECTING)
            job.cancel()
            scope.launch {
                job.join()
                stopping = false
                if (after != null) after() else show(target)
            }
        } else if (after != null) after() else show(target)
    }

    private fun renderStats(s: StreamStats) {
        val contacts = s.contacts.toMap()
        headMap?.contacts = contacts
        contactMessage?.apply {
            text = HeadMapView.describe(contacts)
            setTextColor(if (contacts.values.all { it }) contactOk else spark)
        }
        val battery = if (s.battery.isFinite() && s.battery in 0f..100f) "${s.battery.toInt()}%" else "?"
        metrics?.text = "Battery $battery      ${s.rate} Hz      lost samples ${s.missed + s.discarded}"
    }

    private fun back() {
        if (stopping) return
        when (screen) {
            Screen.SERVER -> { captureForm(); finish() }
            Screen.DEVICE -> { cancelScan(); show(Screen.SERVER) }
            Screen.CONNECTING, Screen.STATUS, Screen.MANUAL -> endSession(setupScreen(), "Session ended. You can connect HALO again.")
        }
    }
    @Deprecated("Legacy Android back navigation")
    override fun onBackPressed() { back() }

    override fun onStart() { super.onStart(); visible = true }
    override fun onStop() {
        captureForm()
        visible = false
        if (running || runJob?.isCompleted == false) {
            endSession(setupScreen(), "Streaming stopped after leaving the app. Connect HALO again.")
        } else if (scanning) {
            cancelScan(); deviceMessage = "Search stopped. You can start it again."; show(Screen.DEVICE)
        }
        super.onStop()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        captureForm()
        outState.putString("endpoint", serverUrl); outState.putInt("player", playerNumber)
        outState.putBoolean("manual_mode", manualMode)
        super.onSaveInstanceState(outState)
    }
    override fun onDestroy() {
        sessionGeneration++; cancelScan(); scope.cancel()
        haloScope?.cancel(); haloScope = null; client = null
        super.onDestroy()
    }

    // ---------------------------------------------------------------- widoki

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun row() = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
    private fun rounded(color: Int, radius: Int = 16) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
    private fun roundedStroke(color: Int, stroke: Int, width: Int, radius: Int) = rounded(color, radius).apply { setStroke(dp(width), stroke) }
    private fun oval(color: Int) = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(color) }
    private fun pressable(normal: Drawable, pressed: Drawable, disabled: Drawable? = null) = StateListDrawable().apply {
        if (disabled != null) addState(intArrayOf(-android.R.attr.state_enabled), disabled)
        addState(intArrayOf(android.R.attr.state_pressed), pressed)
        addState(intArrayOf(), normal)
    }
    private fun space(parent: LinearLayout, size: Int) { parent.addView(View(this), LinearLayout.LayoutParams(1, dp(size))) }

    private fun text(parent: LinearLayout, value: String, size: Int, color: Int = ink) = TextView(this).apply {
        text = value; textSize = size.toFloat(); setTextColor(color); setPadding(0, dp(3), 0, dp(3))
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }

    /** A form question in sentence case, e.g. "Which player are you?". */
    private fun label(parent: LinearLayout, value: String) = TextView(this).apply {
        text = value; textSize = 15f; typeface = mediumFace; setTextColor(ink)
        setPadding(0, dp(16), 0, dp(8))
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }

    private fun field(parent: LinearLayout, hintText: String, value: String, type: Int) = EditText(this).apply {
        hint = hintText; textSize = 18f; setSingleLine(true); inputType = type; setText(value)
        setTextColor(ink); setHintTextColor(Color.rgb(0xa3, 0xa7, 0xc2)); minHeight = dp(58)
        setPadding(dp(16), dp(14), dp(16), dp(14))
        background = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_focused), roundedStroke(paper, wave, 2, 16))
            addState(intArrayOf(), roundedStroke(paper, line, 1, 16))
        }
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }

    /** Player choice: a big numeral, because that is what the game shows next to the player. */
    private fun playerTile(number: Int) = RadioButton(this).apply {
        id = number; buttonDrawable = null; gravity = Gravity.CENTER
        text = SpannableStringBuilder().apply {
            append(number.toString())
            setSpan(AbsoluteSizeSpan(dp(46)), 0, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            setSpan(TypefaceSpan("sans-serif-condensed"), 0, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            append("\nplayer")
        }
        textSize = 14f; typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD); setLineSpacing(0f, 0.85f)
        contentDescription = "Player $number"
        setTextColor(ColorStateList(arrayOf(intArrayOf(android.R.attr.state_checked), intArrayOf()), intArrayOf(Color.WHITE, ink)))
        background = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_checked), rounded(wave, 22))
            addState(intArrayOf(), roundedStroke(paper, line, 1, 22))
        }
    }

    /** A way of playing: line icon, name, one sentence on what it means. */
    private fun option(optionId: Int, kind: ModeIcon.Kind, title: String, description: String) = RadioButton(this).apply {
        id = optionId; buttonDrawable = null
        text = SpannableStringBuilder().apply {
            append(title)
            setSpan(TypefaceSpan("sans-serif-medium"), 0, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            append("\n")
            val start = length
            append(description)
            setSpan(AbsoluteSizeSpan(dp(14)), start, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            setSpan(ForegroundColorSpan(inkSoft), start, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        textSize = 17f; setTextColor(ink); gravity = Gravity.START or Gravity.CENTER_VERTICAL
        minHeight = dp(80); setPadding(dp(16), dp(14), dp(16), dp(14)); compoundDrawablePadding = dp(16)
        val icon = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_checked), ModeIcon(kind, wave, wave, resources.displayMetrics.density))
            addState(intArrayOf(), ModeIcon(kind, inkSoft, inkSoft, resources.displayMetrics.density))
        }.apply { setBounds(0, 0, dp(40), dp(40)) }
        setCompoundDrawablesRelative(icon, null, null, null)
        background = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_checked), roundedStroke(waveTint, wave, 2, 20))
            addState(intArrayOf(), roundedStroke(paper, line, 1, 20))
        }
    }

    private fun button(parent: LinearLayout, value: String, primary: Boolean = true, click: () -> Unit) = Button(this).apply {
        text = value; textSize = 17f; isAllCaps = false; typeface = mediumFace; minHeight = dp(58)
        gravity = Gravity.CENTER; setPadding(dp(16), dp(12), dp(16), dp(12)); stateListAnimator = null
        backgroundTintList = null
        val surface = if (dark) nightSurface else paper
        val edge = if (dark) nightLine else line
        background = if (primary) pressable(rounded(wave, 999), rounded(wavePressed, 999), rounded(edge, 999))
            else pressable(roundedStroke(surface, edge, 1, 999), roundedStroke(if (dark) nightLine else waveTint, edge, 1, 999))
        setTextColor(ColorStateList(arrayOf(intArrayOf(-android.R.attr.state_enabled), intArrayOf()),
            intArrayOf(if (dark) nightSoft else inkSoft, if (primary) Color.WHITE else if (dark) nightInk else ink)))
        setOnClickListener { click() }
        parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(5); bottomMargin = dp(5) })
    }

    /** Quiet action without a box, e.g. "Server needs a token?". */
    private fun textButton(parent: LinearLayout, value: String) = Button(this).apply {
        text = value; textSize = 15f; isAllCaps = false; typeface = mediumFace; minHeight = dp(48)
        gravity = Gravity.START or Gravity.CENTER_VERTICAL; setPadding(0, 0, 0, 0); stateListAnimator = null
        backgroundTintList = null; background = null
        setTextColor(if (dark) Color.rgb(0xa9, 0xa0, 0xff) else wave)
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }
}
