package com.neurotec.minimalgui

import android.app.Activity
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.neurotec.brainaccess.core.BrainAccessClient
import com.neurotec.brainaccess.transport.BlePermissions
import com.neurotec.brainaccess.transport.NordicTransport
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Minimal standalone example for the BrainAccessKit SDK: scan -> connect -> stream typed
 * [com.neurotec.brainaccess.core.EegChunk]s, showing live sample count, per-channel electrode
 * contact, cumulative missed (gap-filled) samples, battery, and the phone's Bluetooth state.
 *
 * Plain Android Views only (no UI framework). The SDK is consumed from app/libs/ (see README).
 */
class MainActivity : Activity() {

    private val ui = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private lateinit var client: BrainAccessClient
    private lateinit var status: TextView
    private var runJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        client = BrainAccessClient(NordicTransport(this))
        status = TextView(this).apply {
            setPadding(32, 32, 32, 32)
            text = "Idle. Tap to start."
        }
        val button = Button(this).apply {
            text = "Scan, connect & stream"
            setOnClickListener { ensurePermissionsThenRun() }
        }
        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                addView(button)
                addView(ScrollView(this@MainActivity).apply { addView(status) })
            },
        )
        // The phone's Bluetooth adapter on/off, observed reactively.
        ui.launch {
            client.bluetoothState.collect { on ->
                if (!on) show("Bluetooth is OFF — enable it, then tap to scan.")
            }
        }
    }

    private fun ensurePermissionsThenRun() {
        // The SDK never requests permissions; the app does. BlePermissions.required is the set
        // the running OS needs (API 31+: BLUETOOTH_SCAN/CONNECT; API <=30: ACCESS_FINE_LOCATION).
        val missing = BlePermissions.required.filter {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) run() else requestPermissions(missing.toTypedArray(), REQ_BLE)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_BLE) return
        if (grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            run()
        } else {
            show("Bluetooth permissions denied.")
        }
    }

    private fun run() {
        runJob?.cancel()
        runJob = ui.launch {
            try {
                show("Scanning…")
                val device = client.scan().first()
                show("Found ${device.name} (${device.model}). Connecting…")
                val session = client.connect(device).getOrThrow()
                ui.launch { session.state.collect { show("State: $it") } }

                var total = 0L
                session.stream().collect { chunk ->
                    total += chunk.sampleCount
                    val connected = chunk.contact.count { it }
                    show(
                        "Streaming ${device.name}\n" +
                            "samples: $total\n" +
                            "rate: ${chunk.srate} Hz · channels: ${chunk.channels.size} · hw: ${session.hardware}\n" +
                            "accel (m/s²): ${chunk.accel != null} · gyro (deg/s): ${chunk.gyro != null}\n" +
                            "contact: $connected/${chunk.contact.size} connected\n" +
                            "missed (gap-filled): ${session.missedSamples.value}\n" +
                            "battery: ${chunk.batteryPct.toInt()}%",
                    )
                }
            } catch (e: Throwable) {
                show("Error: ${e.message}")
            }
        }
    }

    private fun show(message: String) {
        status.text = message
    }

    override fun onDestroy() {
        super.onDestroy()
        ui.cancel()
    }

    private companion object {
        const val REQ_BLE = 1
    }
}
