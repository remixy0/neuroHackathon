package pl.halorush.controller

import android.app.Activity
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
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
import java.net.URI

class MainActivity : Activity() {
    private enum class Screen { SERVER, DEVICE, CONNECTING, STATUS, MANUAL }
    private data class DeviceChoice(val name: String, val id: String, val open: suspend () -> DeviceSession)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var client: BrainAccessClient
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
    private var manualController: ManualController? = null
    private var manualFeedback: TextView? = null
    private var pressCount = 0L
    private var lastManualFeedback = "Gotowy do gry"
    private var modeField: RadioGroup? = null
    private var phase: ConnectionPhase? = null
    private var connectionMessage = ""
    private var connectionError: String? = null
    private var deviceMessage = "Włącz opaskę i trzymaj ją blisko telefonu."
    private var latestStats: StreamStats? = null
    private var lastCommand = "—"

    private var endpointField: EditText? = null
    private var tokenField: EditText? = null
    private var playerField: RadioGroup? = null
    private var formError: TextView? = null
    private var deviceList: LinearLayout? = null
    private var deviceStatus: TextView? = null
    private var searchButton: Button? = null
    private var metrics: TextView? = null
    private var contact: TextView? = null
    private var command: TextView? = null

    private val green = Color.rgb(199, 255, 97)
    private val ink = Color.rgb(16, 21, 16)
    private val white = Color.rgb(241, 246, 235)
    private val muted = Color.rgb(159, 174, 156)
    private val amber = Color.rgb(255, 191, 105)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        client = BrainAccessClient(NordicTransport(applicationContext))
        val prefs = getSharedPreferences("controller", MODE_PRIVATE)
        serverUrl = savedInstanceState?.getString("endpoint") ?: prefs.getString("endpoint", "").orEmpty()
        playerNumber = (savedInstanceState?.getInt("player") ?: prefs.getInt("player", 1)).coerceIn(1, 2)
        manualMode = savedInstanceState?.getBoolean("manual_mode") ?: prefs.getBoolean("manual_mode", false)
        show(Screen.SERVER)
        if (Build.VERSION.SDK_INT >= 33) {
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT) { back() }
        }
        scope.launch {
            client.bluetoothState.collect { on ->
                if (!on && !manualMode) {
                    if (running) endSession(Screen.DEVICE, "Bluetooth jest wyłączony. Włącz go i wybierz HALO ponownie.")
                    else if (screen == Screen.DEVICE) {
                        cancelScan()
                        deviceMessage = "Włącz Bluetooth, aby wyszukać HALO."
                        show(Screen.DEVICE)
                    }
                } else if (screen == Screen.DEVICE && !running && !stopping) {
                    deviceMessage = "Bluetooth jest włączony. Możesz wyszukać opaskę."
                    show(Screen.DEVICE)
                }
            }
        }
    }

    private fun show(next: Screen) {
        screen = next
        endpointField = null; tokenField = null; playerField = null; formError = null
        deviceList = null; deviceStatus = null; searchButton = null
        metrics = null; contact = null; command = null; modeField = null; manualFeedback = null
        setControllerFullscreen(next == Screen.MANUAL)
        if (next == Screen.MANUAL) {
            manualScreen()
            return
        }
        root = column().apply { setPadding(dp(24), dp(20), dp(24), dp(28)) }
        val scroll = ScrollView(this).apply { addView(root); isFillViewport = true; setBackgroundColor(ink) }
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
        header(next)
        when (next) {
            Screen.SERVER -> serverScreen()
            Screen.DEVICE -> deviceScreen()
            Screen.CONNECTING -> connectingScreen()
            Screen.STATUS -> statusScreen()
            Screen.MANUAL -> manualScreen()
        }
    }

    private fun header(current: Screen) {
        text(root, "HALO / RUSH", 13, green).letterSpacing = 0.22f
        space(root, 20)
        val steps = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val labels = if (manualMode) listOf("Serwer", "Łączenie", "Kontroler") else listOf("Serwer", "Opaska", "Łączenie", "Status")
        val position = if (manualMode) when (current) { Screen.SERVER -> 0; Screen.CONNECTING -> 1; else -> 2 } else current.ordinal
        labels.forEachIndexed { index, title ->
            val step = column()
            step.addView(View(this).apply {
                background = rounded(if (index <= position) green else Color.rgb(48, 58, 45), 2)
            }, LinearLayout.LayoutParams(-1, dp(3)))
            text(step, "${index + 1}  $title", 11, if (index == position) green else muted)
            steps.addView(step, LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = dp(6) })
        }
        root.addView(steps)
        space(root, 22)
    }

    private fun title(value: String, description: String) {
        text(root, value, 32).setTypeface(Typeface.DEFAULT, Typeface.BOLD)
        text(root, description, 15, muted)
        space(root, 22)
    }

    private fun serverScreen() {
        title("Zacznij od serwera", "Podaj adres serwera i wybierz sposób sterowania.")
        val form = card(root)
        text(form, "Adres serwera", 14)
        endpointField = field(form, "ws://192.168.1.20:8766/ws/controller", serverUrl,
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        space(form, 12)
        text(form, "Token dostępu", 14)
        text(form, "Opcjonalny. Dla serwera testowego zostaw puste pole.", 12, muted)
        tokenField = field(form, "Token", bearerToken,
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD).apply { isSaveEnabled = false }
        space(form, 12)
        text(form, "Wybierz gracza", 14)
        playerField = RadioGroup(this).apply {
            orientation = RadioGroup.HORIZONTAL
            for (number in 1..2) addView(RadioButton(this@MainActivity).apply {
                id = number; text = "Gracz $number"; minHeight = dp(48)
                setTextColor(white); setPadding(0, 0, dp(24), 0)
            })
            check(playerNumber)
            form.addView(this)
        }
        space(form, 12)
        text(form, "Sposób sterowania", 14)
        modeField = RadioGroup(this).apply {
            orientation = RadioGroup.VERTICAL
            addView(RadioButton(this@MainActivity).apply { id = R.id.mode_halo; text = "Opaska HALO · sygnał EEG"; minHeight = dp(48); setTextColor(white) })
            addView(RadioButton(this@MainActivity).apply { id = R.id.mode_manual; text = "Kontroler ręczny · bez opaski"; minHeight = dp(48); setTextColor(white) })
            check(if (manualMode) R.id.mode_manual else R.id.mode_halo)
            form.addView(this)
        }
        formError = text(root, "", 14, amber).apply {
            visibility = View.GONE; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        space(root, 18)
        button(root, "Dalej") { continueToDevice() }
        space(root, 12)
        text(root, "Telefon i komputer z serwerem muszą być w tej samej sieci. Użyj adresu komputera, nie localhost.", 13, muted)
    }

    private fun captureForm() {
        endpointField?.let { serverUrl = it.text.toString().trim() }
        tokenField?.let { bearerToken = it.text.toString() }
        playerField?.let { playerNumber = it.checkedRadioButtonId }
        modeField?.let { manualMode = it.checkedRadioButtonId == R.id.mode_manual }
    }

    private fun continueToDevice() {
        captureForm()
        try {
            val uri = URI(serverUrl)
            require(uri.scheme in listOf("ws", "wss") && !uri.host.isNullOrBlank() &&
                uri.userInfo == null && uri.fragment == null && (uri.port == -1 || uri.port in 1..65535))
            require(!bearerToken.contains('\n') && !bearerToken.contains('\r'))
        } catch (_: Exception) {
            formError?.apply { text = "Podaj poprawny adres ws:// lub wss://. Token nie może zawierać nowych linii."; visibility = View.VISIBLE }
            return
        }
        bearerToken = bearerToken.trim()
        getSharedPreferences("controller", MODE_PRIVATE).edit().putString("endpoint", serverUrl)
            .putInt("player", playerNumber).putBoolean("manual_mode", manualMode).apply()
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(root.windowToken, 0)
        deviceMessage = "Włącz opaskę i trzymaj ją blisko telefonu."
        if (manualMode) connectManual() else show(Screen.DEVICE)
    }

    private fun deviceScreen() {
        title("Wybierz swoją opaskę", "Wyszukaj HALO przez Bluetooth i dotknij nazwy urządzenia.")
        val summary = card(root)
        text(summary, "GRACZ $playerNumber  /  SERWER", 11, green)
        text(summary, serverUrl, 14)
        space(root, 18)
        deviceStatus = text(root, deviceMessage, 15, muted).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        searchButton = button(root, if (scanning) "Szukanie opasek…" else "Szukaj HALO") { ensurePermissions() }
            .apply { isEnabled = !scanning }
        if (scanning) root.addView(ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = true
        }, LinearLayout.LayoutParams(-1, dp(6)))
        space(root, 12)
        deviceList = column().also { root.addView(it) }
        renderDevices()
        space(root, 18)
        button(root, "Wstecz · zmień serwer", false) { cancelScan(); show(Screen.SERVER) }
        text(root, "Nie widzisz opaski? Sprawdź, czy jest włączona i rozłączona z innym urządzeniem. Na Androidzie 11 i starszym włącz również lokalizację.", 13, muted)
    }

    private fun renderDevices() {
        val list = deviceList ?: return
        list.removeAllViews()
        if (choices.isEmpty()) {
            val empty = card(list)
            text(empty, if (scanning) "Szukamy w pobliżu" else "Twoje HALO pojawi się tutaj", 18)
            text(empty, "Wybierzesz opaskę po jej nazwie i identyfikatorze.", 13, muted)
        } else choices.values.forEach { device ->
            button(list, "${device.name}\n${device.id}  →", false) {
                cancelScan()
                selected = device
                connect()
            }
        }
    }

    private fun ensurePermissions() {
        if (screen != Screen.DEVICE || stopping || running) return
        if (!client.bluetoothState.value) {
            deviceMessage = "Najpierw włącz Bluetooth w ustawieniach telefonu."
            show(Screen.DEVICE); return
        }
        val missing = BlePermissions.required.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) scan() else requestPermissions(missing.toTypedArray(), 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 1 || !visible || screen != Screen.DEVICE) return
        if (grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) scan()
        else {
            deviceMessage = "Zezwól na dostęp do Bluetooth, aby wyszukać opaskę. Możesz spróbować ponownie."
            show(Screen.DEVICE)
        }
    }

    private fun scan() {
        if (scanning || running || stopping) return
        cancelScan()
        val generation = scanGeneration
        choices.clear(); scanning = true
        deviceMessage = "Wyszukiwanie trwa do 15 sekund. Możesz od razu wybrać znalezioną opaskę."
        show(Screen.DEVICE)
        scanJob = scope.launch {
            try {
                withTimeout(15_000) {
                    client.scan().collect { device ->
                        if (generation == scanGeneration && screen == Screen.DEVICE &&
                            device.model.toString().contains("HALO", ignoreCase = true)) {
                            val key = device.id.toString()
                            if (!choices.containsKey(key)) {
                                choices[key] = DeviceChoice(device.name, key) { client.connect(device).getOrThrow() }
                                renderDevices()
                            }
                        }
                    }
                }
            } catch (_: TimeoutCancellationException) {
                deviceMessage = if (choices.isEmpty()) "Nie znaleziono HALO. Sprawdź opaskę i wyszukaj ponownie." else "Wybierz opaskę z listy."
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { deviceMessage = "Nie udało się wyszukać opaski: ${e.message}"
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
            stopping -> "Kończymy sesję"
            error != null -> "Nie udało się połączyć"
            phase == ConnectionPhase.RETRYING -> "Przywracamy połączenie"
            else -> "Łączymy Twój kontroler"
        }, if (manualMode) "Kontroler ekranowy" else selected?.name ?: "HALO")
        val progress = card(root)
        if (error == null) {
            progress.addView(ProgressBar(this).apply { indeterminateTintList = ColorStateList.valueOf(green) },
                LinearLayout.LayoutParams(dp(48), dp(48)).apply { gravity = Gravity.CENTER_HORIZONTAL; bottomMargin = dp(18) })
        }
        text(progress, error ?: connectionMessage, 17, if (error != null) amber else green).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        if (!stopping && error == null) {
            space(progress, 16)
            val step = if (manualMode) { if (phase == ConnectionPhase.REGISTERING) 1 else 0 } else when (phase) {
                null -> 0
                ConnectionPhase.SERVER, ConnectionPhase.RETRYING -> 1
                else -> 2
            }
            val steps = if (manualMode) listOf("Połączenie z serwerem", "Potwierdzenie trybu ręcznego")
                else listOf("Połączenie z HALO", "Połączenie z serwerem", "Potwierdzenie sesji")
            steps.forEachIndexed { index, label ->
                text(progress, "${if (index < step) "✓" else if (index == step) "●" else "○"}   $label", 15,
                    if (index <= step) white else muted)
            }
        }
        space(root, 18)
        text(root, "Gracz $playerNumber\n$serverUrl", 14, muted)
        space(root, 18)
        if (error != null) {
            button(root, "Spróbuj ponownie") { if (manualMode) connectManual() else connect() }
            if (!manualMode) button(root, "Wybierz inną opaskę", false) { choices.clear(); show(Screen.DEVICE) }
            button(root, "Zmień serwer", false) { show(Screen.SERVER) }
        } else {
            button(root, if (stopping) "Rozłączanie…" else "Anuluj", false) {
                endSession(setupScreen(), "Połączenie anulowane. Wybierz opaskę lub wyszukaj ponownie.")
            }.isEnabled = !stopping
        }
    }

    private fun statusScreen() {
        title("Jesteś połączony", "Sygnał z HALO trafia do serwera. Możesz rozpocząć grę.")
        val summary = card(root)
        text(summary, "●  TRANSMISJA AKTYWNA", 12, green)
        text(summary, selected?.name ?: "HALO", 22).setTypeface(Typeface.DEFAULT, Typeface.BOLD)
        text(summary, "Gracz $playerNumber  ·  $serverUrl", 13, muted)
        space(root, 16)
        val signal = card(root)
        text(signal, "SYGNAŁ NA ŻYWO", 11, muted)
        metrics = text(signal, "Czekamy na pierwsze próbki…", 18)
        space(signal, 12)
        text(signal, "KONTAKT ELEKTROD", 11, muted)
        contact = text(signal, "Oczekiwanie na dane z opaski", 15, muted)
        space(root, 16)
        val action = card(root)
        text(action, "OSTATNIA KOMENDA SERWERA", 11, muted)
        command = text(action, lastCommand, 28, green)
        text(action, "Serwer testowy tylko odbiera dane — komenda może pozostać pusta.", 12, muted)
        latestStats?.let { renderStats(it) }
        space(root, 18)
        button(root, "Zakończ sesję") { endSession(Screen.DEVICE, "Sesja zakończona. Możesz ponownie połączyć HALO.") }
        button(root, "Zmień serwer", false) { endSession(Screen.SERVER) }
        text(root, "Pozostaw ten ekran otwarty. Wyjście z aplikacji lub zablokowanie telefonu zatrzymuje transmisję.", 13, muted)
    }

    private fun manualScreen() {
        // This screen intentionally has no wizard header, explanatory cards or scrolling.
        root = column().apply {
            setPadding(dp(12), dp(8), dp(12), dp(6))
            setBackgroundColor(Color.rgb(55, 63, 66))
        }
        val shell = FrameLayout(this).apply { setBackgroundColor(Color.rgb(55, 63, 66)); addView(root, FrameLayout.LayoutParams(-1, -1)) }
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
        val toolbar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        root.addView(toolbar, LinearLayout.LayoutParams(-1, dp(52)))
        val players = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = rounded(Color.rgb(70, 80, 84), 30)
            setPadding(dp(3), dp(2), dp(3), dp(2))
        }
        toolbar.addView(players, LinearLayout.LayoutParams(-2, dp(52)))
        for (number in 1..2) {
            Button(this).apply {
                text = "GRACZ $number"; textSize = 12f; isAllCaps = false
                typeface = Typeface.create("sans-serif", Typeface.BOLD)
                setTextColor(if (number == playerNumber) white else muted)
                backgroundTintList = null
                background = rounded(if (number == playerNumber) Color.rgb(36, 41, 97) else Color.TRANSPARENT, 26)
                minWidth = 0; minimumWidth = 0; setPadding(0, 0, 0, 0)
                isEnabled = number != playerNumber
                setOnClickListener { switchManualPlayer(number) }
                players.addView(this, LinearLayout.LayoutParams(dp(74), dp(48)))
            }
        }
        TextView(this).apply {
            text = "● ONLINE"; textSize = 11f; setTextColor(green); gravity = Gravity.CENTER
            contentDescription = "Połączono z serwerem"
            toolbar.addView(this, LinearLayout.LayoutParams(0, -1, 1f))
        }
        Button(this).apply {
            text = "✕"; textSize = 20f; setTextColor(white)
            contentDescription = "Zakończ / zmień tryb"
            minWidth = 0; minimumWidth = 0; setPadding(0, 0, 0, 0)
            backgroundTintList = null; background = rounded(Color.rgb(70, 80, 84), 24)
            setOnClickListener { endSession(Screen.SERVER) }
            toolbar.addView(this, LinearLayout.LayoutParams(dp(48), dp(48)))
        }
        space(root, 8)
        root.addView(RetroPadView(this) { key ->
            if (manualController?.press(key) == true) {
                pressCount++
                lastManualFeedback = "${key.uppercase()}  →  GRACZ $playerNumber   ·   wysłano $pressCount"
            } else lastManualFeedback = "Brak połączenia — przycisk nie został wysłany"
            manualFeedback?.text = lastManualFeedback
        }, LinearLayout.LayoutParams(-1, 0, 1f))
        manualFeedback = TextView(this).apply {
            text = lastManualFeedback; textSize = 11f; typeface = Typeface.MONOSPACE
            setTextColor(muted); gravity = Gravity.CENTER_VERTICAL; setSingleLine(true)
            root.addView(this, LinearLayout.LayoutParams(-1, dp(24)))
        }
    }

    @Suppress("DEPRECATION")
    private fun setControllerFullscreen(enabled: Boolean) {
        if (Build.VERSION.SDK_INT >= 30) {
            window.insetsController?.apply {
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
            } else View.SYSTEM_UI_FLAG_VISIBLE
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
        connectionMessage = "Łączenie kontrolera z serwerem…"
        show(Screen.CONNECTING)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val controller = ManualController { update -> sessionUi(generation) {
            phase = update.phase; connectionMessage = update.message
            if (phase == ConnectionPhase.STREAMING) { pressCount = 0; lastManualFeedback = "Gotowy do gry"; show(Screen.MANUAL) }
            else show(Screen.CONNECTING)
        } }
        manualController = controller
        runJob = scope.launch {
            var failure: String? = null
            try {
                withContext(Dispatchers.Default) { controller.run(serverUrl, bearerToken, playerNumber) }
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { failure = e.message ?: "Nie udało się połączyć kontrolera."
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
        if (running || stopping || runJob?.isCompleted == false) return
        cancelScan()
        running = true
        val generation = ++sessionGeneration
        connectionError = null; phase = null; latestStats = null; lastCommand = "—"
        connectionMessage = "Nawiązywanie połączenia Bluetooth…"
        show(Screen.CONNECTING)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val controller = Controller(
            { update -> sessionUi(generation) {
                phase = update.phase; connectionMessage = update.message
                if (phase == ConnectionPhase.STREAMING) show(Screen.STATUS)
                else { latestStats = null; lastCommand = "—"; show(Screen.CONNECTING) }
            } },
            { value -> sessionUi(generation) { latestStats = value; if (screen == Screen.STATUS) renderStats(value) } },
            { direction -> sessionUi(generation) {
                lastCommand = when (direction) {
                    "left" -> "←  W LEWO"; "right" -> "→  W PRAWO"; "up" -> "↑  SKOK"; else -> "↓  ŚLIZG"
                }
                command?.text = lastCommand
            } },
        )
        runJob = scope.launch {
            var failure: String? = null
            try {
                val session = withTimeout(20_000) { device.open() }
                withContext(Dispatchers.Default) { controller.run(session, serverUrl, bearerToken, playerNumber) }
            } catch (_: TimeoutCancellationException) { failure = "HALO nie odpowiedziało w terminie. Sprawdź opaskę i spróbuj ponownie."
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { failure = e.message ?: "Wystąpił błąd połączenia. Spróbuj ponownie."
            } finally {
                // A BLE teardown failure must not strand the wizard on the disconnecting screen.
                withContext(NonCancellable) {
                    withTimeoutOrNull(5_000) { runCatching { client.disconnectAll() } }
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

    private fun endSession(target: Screen, message: String = "Wybierz opaskę, aby rozpocząć nową sesję.", after: (() -> Unit)? = null) {
        if (stopping) return
        cancelScan(); sessionGeneration++
        deviceMessage = message
        choices.clear()
        connectionError = null
        val job = runJob
        if (job != null && !job.isCompleted) {
            stopping = true
            connectionMessage = if (manualMode) "Rozłączamy kontroler…" else "Zatrzymujemy przesyłanie danych i rozłączamy HALO…"
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
        val battery = if (s.battery.isFinite() && s.battery in 0f..100f) "${s.battery.toInt()}%" else "—"
        metrics?.text = "${s.rate} Hz   ·   bateria $battery\n${s.samples} wysłanych próbek\nUtracone BLE: ${s.missed}   ·   Opóźnione: ${s.discarded}"
        contact?.text = s.contacts.joinToString("    ") { (name, good) -> "${if (good) "●" else "○"} $name" }
        contact?.setTextColor(if (s.contacts.all { it.second }) green else amber)
    }

    private fun back() {
        if (stopping) return
        when (screen) {
            Screen.SERVER -> { captureForm(); finish() }
            Screen.DEVICE -> { cancelScan(); show(Screen.SERVER) }
            Screen.CONNECTING, Screen.STATUS, Screen.MANUAL -> endSession(setupScreen(), "Sesja zakończona. Możesz ponownie połączyć HALO.")
        }
    }
    @Deprecated("Legacy Android back navigation")
    override fun onBackPressed() { back() }

    override fun onStart() { super.onStart(); visible = true }
    override fun onStop() {
        captureForm()
        visible = false
        if (running || runJob?.isCompleted == false) {
            endSession(setupScreen(), "Transmisja zatrzymana po opuszczeniu aplikacji. Połącz HALO ponownie.")
        } else if (scanning) {
            cancelScan(); deviceMessage = "Wyszukiwanie zatrzymane. Możesz uruchomić je ponownie."; show(Screen.DEVICE)
        }
        super.onStop()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        captureForm()
        outState.putString("endpoint", serverUrl); outState.putInt("player", playerNumber)
        outState.putBoolean("manual_mode", manualMode)
        super.onSaveInstanceState(outState)
    }
    override fun onDestroy() { sessionGeneration++; cancelScan(); scope.cancel(); super.onDestroy() }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun rounded(color: Int, radius: Int = 16) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
    private fun space(parent: LinearLayout, size: Int) { parent.addView(View(this), LinearLayout.LayoutParams(1, dp(size))) }
    private fun card(parent: LinearLayout) = column().apply {
        background = rounded(Color.rgb(29, 38, 27)); setPadding(dp(18), dp(16), dp(18), dp(16))
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }
    private fun text(parent: LinearLayout, value: String, size: Int, color: Int = white) = TextView(this).apply {
        text = value; textSize = size.toFloat(); setTextColor(color); setPadding(0, dp(5), 0, dp(5))
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }
    private fun field(parent: LinearLayout, hintText: String, value: String, type: Int) = EditText(this).apply {
        hint = hintText; textSize = 15f; setSingleLine(true); inputType = type; setText(value)
        setTextColor(white); setHintTextColor(muted); minHeight = dp(52)
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }
    private fun button(parent: LinearLayout, value: String, primary: Boolean = true, click: () -> Unit) = Button(this).apply {
        text = value; textSize = 15f; isAllCaps = false; minHeight = dp(54)
        gravity = Gravity.CENTER; setPadding(dp(16), dp(12), dp(16), dp(12))
        backgroundTintList = ColorStateList.valueOf(if (primary) green else Color.rgb(38, 49, 35))
        setTextColor(if (primary) ink else white); setOnClickListener { click() }
        parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(4); bottomMargin = dp(4) })
    }
}
