package pl.halorush.controller

import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.*
import com.neurotec.brainaccess.core.BrainAccessClient
import com.neurotec.brainaccess.core.DeviceSession
import com.neurotec.brainaccess.transport.BlePermissions
import com.neurotec.brainaccess.transport.NordicTransport
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collect
import java.net.URI

class MainActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var client: BrainAccessClient
    private lateinit var controller: Controller
    private lateinit var root: LinearLayout
    private lateinit var devices: LinearLayout
    private lateinit var endpoint: EditText
    private lateinit var token: EditText
    private lateinit var player: RadioGroup
    private lateinit var scanButton: Button
    private lateinit var stopButton: Button
    private lateinit var status: TextView
    private lateinit var metrics: TextView
    private lateinit var contact: TextView
    private lateinit var command: TextView
    private var scanJob: Job? = null
    private var runJob: Job? = null
    private var visible = false
    private val seen = mutableSetOf<String>()
    private val green = Color.rgb(199, 255, 97)
    private val muted = Color.rgb(159, 174, 156)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        client = BrainAccessClient(NordicTransport(applicationContext))
        controller = Controller(
            { message -> runOnUiThread { status.text = message } },
            { value -> runOnUiThread { renderStats(value) } },
            { direction -> runOnUiThread {
                command.text = when (direction) {
                    "left" -> "←  W LEWO"; "right" -> "→  W PRAWO"
                    "up" -> "↑  SKOK"; else -> "↓  ŚLIZG"
                }
            } },
        )
        buildUi()
        scope.launch {
            client.bluetoothState.collect { on ->
                if (!on) { stop(); status.text = "Włącz Bluetooth, aby połączyć HALO." }
            }
        }
    }

    private fun buildUi() {
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(24), dp(24), dp(24), dp(24))
        }
        val scroll = ScrollView(this).apply { addView(root); isFillViewport = true }
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            insets
        }
        setContentView(scroll)
        label("HALO / RUSH", 14, green).apply { letterSpacing = 0.22f }
        label("Twój umysł.\nTwój kontroler.", 34).apply { setTypeface(typeface, Typeface.BOLD) }
        label("Połącz opaskę i przesyłaj sygnał do gry.", 15, muted)
        gap(20)
        status = label("Gotowy do połączenia", 16, green).apply {
            background = panel(); setPadding(dp(16), dp(16), dp(16), dp(16))
        }
        gap(22)
        label("01  /  POŁĄCZENIE", 12, muted)
        val prefs = getSharedPreferences("controller", MODE_PRIVATE)
        label("Adres backendu", 14)
        endpoint = field("ws://192.168.1.20:8765/ws/controller", false).apply {
            setText(prefs.getString("endpoint", ""))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        label("Token dostępu · opcjonalny", 14)
        token = field("Bearer token", true)
        label("Twój gracz", 14)
        player = RadioGroup(this).apply {
            orientation = RadioGroup.HORIZONTAL
            for (number in 1..2) addView(RadioButton(this@MainActivity).apply {
                id = number; text = "Gracz $number"; setPadding(0, dp(8), dp(24), dp(8))
            })
            check(prefs.getInt("player", 1))
        }
        root.addView(player)
        gap(16)
        label("02  /  TWOJA OPASKA", 12, muted)
        scanButton = button("Szukaj HALO") { ensurePermissions() }
        devices = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(devices)
        stopButton = button("Zatrzymaj i rozłącz") { stop() }.apply { isEnabled = false }
        gap(20)
        label("03  /  SYGNAŁ NA ŻYWO", 12, muted)
        metrics = label("— Hz    /    — próbek\nBateria —    ·    Utracone BLE —", 17)
        contact = label("Kontakt elektrod pojawi się po połączeniu.", 14, muted)
        gap(16)
        label("OSTATNIA KOMENDA BACKENDU", 12, muted)
        command = label("—", 30, green)
        gap(20)
        label("Pozostaw ten ekran otwarty podczas gry. Wyjście z aplikacji zatrzymuje transmisję. Telefon i backend muszą mieć połączenie sieciowe.", 13, muted)
    }

    private fun ensurePermissions() {
        try {
            val uri = URI(endpoint.text.toString().trim())
            require(uri.scheme in listOf("ws", "wss") && !uri.host.isNullOrBlank() &&
                uri.userInfo == null && uri.fragment == null && (uri.port == -1 || uri.port in 1..65535))
            require(!token.text.contains('\n') && !token.text.contains('\r'))
        } catch (_: Exception) {
            status.text = "Wpisz poprawny adres ws:// lub wss:// oraz token bez nowych linii."
            return
        }
        if (!client.bluetoothState.value) { status.text = "Najpierw włącz Bluetooth."; return }
        val missing = BlePermissions.required.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) scan() else requestPermissions(missing.toTypedArray(), 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 1 || !visible) return
        if (grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) scan()
        else status.text = "Potrzebna jest zgoda na Bluetooth. Na Androidzie 11 i starszym włącz też lokalizację."
    }

    private fun scan() {
        if (scanJob?.isActive == true || runJob?.isCompleted == false) return
        devices.removeAllViews(); seen.clear(); busy(true)
        metrics.text = "— Hz    /    — próbek"; contact.text = "Oczekiwanie na sygnał"; command.text = "—"
        status.text = "Szukam opasek HALO… wybierz swoją z listy."
        scanJob = scope.launch {
            try {
                withTimeout(15_000) {
                    client.scan().collect { device ->
                        if (device.model.toString().contains("HALO", ignoreCase = true) && seen.add(device.id.toString())) {
                            val choice = Button(this@MainActivity).apply {
                                text = "${device.name}\n${device.id}"
                                isAllCaps = false
                                setOnClickListener {
                                    scanJob?.cancel(); devices.removeAllViews()
                                    connect { client.connect(device).getOrThrow() }
                                }
                            }
                            devices.addView(choice)
                        }
                    }
                }
            } catch (_: TimeoutCancellationException) {
                status.text = if (seen.isEmpty()) "Nie znaleziono HALO. Włącz opaskę i sprawdź uprawnienia." else "Wybierz swoją opaskę z listy."
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { status.text = "Skanowanie: ${e.message}"
            } finally { if (runJob?.isCompleted != false) busy(false) }
        }
    }

    private fun connect(open: suspend () -> DeviceSession) {
        val url = endpoint.text.toString().trim()
        val bearer = token.text.toString().trim()
        val selectedPlayer = player.checkedRadioButtonId
        getSharedPreferences("controller", MODE_PRIVATE).edit().putString("endpoint", url)
            .putInt("player", selectedPlayer).apply()
        busy(true)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        status.text = "Łączenie z HALO…"
        runJob = scope.launch {
            try {
                val session = withTimeout(20_000) { open() }
                withContext(Dispatchers.Default) { controller.run(session, url, bearer, selectedPlayer) }
            } catch (_: TimeoutCancellationException) { status.text = "HALO nie odpowiedziało w terminie. Spróbuj ponownie."
            } catch (e: CancellationException) { throw e
            } catch (e: Exception) { status.text = "Zatrzymano: ${e.message}"
            } finally {
                withContext(NonCancellable) { withTimeoutOrNull(5_000) { client.disconnectAll() } }
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                busy(false)
            }
        }
    }

    private fun stop() {
        scanJob?.cancel(); runJob?.cancel(); devices.removeAllViews()
        status.text = "Transmisja zatrzymana"
        if (runJob?.isCompleted != false) busy(false)
    }

    private fun busy(active: Boolean) {
        scanButton.isEnabled = !active; stopButton.isEnabled = active
        endpoint.isEnabled = !active; token.isEnabled = !active
        for (i in 0 until player.childCount) player.getChildAt(i).isEnabled = !active
    }
    private fun renderStats(s: StreamStats) {
        val battery = if (s.battery.isFinite() && s.battery in 0f..100f) "${s.battery.toInt()}%" else "—"
        metrics.text = "${s.rate} Hz    /    ${s.samples} próbek wysłanych\nBateria $battery    ·    Utracone BLE ${s.missed}\nOdrzucone opóźnione: ${s.discarded}"
        contact.text = s.contacts.joinToString("    ") { (name, good) -> "${if (good) "●" else "○"} $name" }
        contact.setTextColor(if (s.contacts.all { it.second }) green else Color.rgb(255, 191, 105))
    }

    override fun onStart() { super.onStart(); visible = true }
    override fun onStop() { visible = false; stop(); super.onStop() }
    override fun onDestroy() { scope.cancel(); controller.release(); super.onDestroy() }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun panel() = GradientDrawable().apply { setColor(Color.rgb(31, 41, 29)); cornerRadius = dp(14).toFloat() }
    private fun gap(size: Int) { root.addView(View(this), LinearLayout.LayoutParams(1, dp(size))) }
    private fun label(value: String, size: Int, color: Int = Color.rgb(241, 246, 235)): TextView = TextView(this).apply {
        text = value; textSize = size.toFloat(); setTextColor(color); setPadding(0, dp(6), 0, dp(6)); root.addView(this)
    }
    private fun field(hintText: String, password: Boolean) = EditText(this).apply {
        hint = hintText; textSize = 15f; setSingleLine(true)
        if (password) inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        root.addView(this, LinearLayout.LayoutParams(-1, dp(52)))
    }
    private fun button(value: String, click: () -> Unit) = Button(this).apply {
        text = value; isAllCaps = false; setOnClickListener { click() }
        root.addView(this, LinearLayout.LayoutParams(-1, dp(56)))
    }
}
