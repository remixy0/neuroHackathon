package pl.halorush.controller

import kotlinx.serialization.json.*

/** One SDK chunk. No filtering, resampling or channel reordering on the phone. */
data class SignalFrame(
    val channels: List<String>, val sampleRate: Int, val count: Int,
    val eeg: FloatArray, val accel: FloatArray?, val gyro: FloatArray?,
    val firstIndex: Long, val wireLastIndex: Long, val hostTimeNs: Long,
    val dummy: BooleanArray, val contact: BooleanArray, val battery: Float,
) {
    init {
        require(channels.isNotEmpty() && channels.distinct().size == channels.size)
        require(sampleRate > 0 && count > 0)
        require(eeg.size == count * channels.size && eeg.all { it.isFinite() })
        require(dummy.size == count && contact.size == channels.size)
        require(firstIndex >= 0)
        for (sensor in listOf(accel, gyro)) {
            require(sensor == null || (sensor.size == count * 3 && sensor.all { it.isFinite() }))
        }
    }
}

object Protocol {
    const val VERSION = 1
    val MANUAL_BUTTONS = setOf("up", "down", "left", "right", "a", "b", "x", "select", "start")
    private fun FloatArray.json() = JsonArray(map { JsonPrimitive(it) })
    private fun BooleanArray.json() = JsonArray(map { JsonPrimitive(it) })
    private fun base(type: String, session: String, block: JsonObjectBuilder.() -> Unit) = buildJsonObject {
        put("type", type); put("version", VERSION); put("session_id", session); block()
    }.toString()

    fun hello(session: String, player: Int, deviceId: String, deviceName: String,
              hardware: String, frame: SignalFrame): String {
        require(player in 1..2)
        return base("hello", session) {
            put("role", "controller"); put("player", player)
            putJsonObject("device") {
                put("id", deviceId); put("name", deviceName); put("hardware", hardware)
                put("sdk", "BrainAccessKit-2.3.1")
            }
            putJsonObject("stream") {
                put("sample_rate_hz", frame.sampleRate)
                put("channels", JsonArray(frame.channels.map { JsonPrimitive(it) }))
                put("layout", "sample_major"); put("eeg_unit", "uV")
                put("accel_unit", "m/s2"); put("gyro_unit", "deg/s")
                put("has_accel", frame.accel != null); put("has_gyro", frame.gyro != null)
            }
        }
    }

    fun samples(session: String, seq: Long, f: SignalFrame, skipped: Long, missed: Long) = base("samples", session) {
        put("seq", seq); put("sample_count", f.count)
        put("first_sample_index", f.firstIndex.toString())
        put("wire_last_sample_index", f.wireLastIndex.toString())
        put("host_time_ns", f.hostTimeNs.toString())
        put("eeg", f.eeg.json()); put("accel", f.accel?.json() ?: JsonNull)
        put("gyro", f.gyro?.json() ?: JsonNull); put("is_dummy", f.dummy.json())
        put("contact", f.contact.json())
        put("battery_pct", if (f.battery.isFinite() && f.battery in 0f..100f) JsonPrimitive(f.battery) else JsonNull)
        put("phone_discarded_samples", skipped.toString()); put("ble_missed_samples", missed.toString())
    }

    fun stop(session: String) = base("stop", session) { put("reason", "user_or_lifecycle") }

    fun manualHello(session: String, player: Int): String {
        require(player in 1..2)
        return base("hello", session) {
            put("role", "controller"); put("mode", "manual"); put("player", player)
        }
    }

    fun manual(session: String, seq: Long, player: Int, button: String): String {
        require(player in 1..2 && button in MANUAL_BUTTONS && seq >= 0)
        return base("manual", session) {
            put("seq", seq); put("id", "$session:$seq"); put("player", player)
            put("button", button); put("action", "press")
        }
    }
}
