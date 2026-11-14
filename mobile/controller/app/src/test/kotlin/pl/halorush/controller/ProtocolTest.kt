package pl.halorush.controller

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

fun fixture() = SignalFrame(
    listOf("O1", "O2", "Fp2", "Fp1"), 250, 2,
    floatArrayOf(1f, 2f, 3f, 4f, 5f, 6f, 7f, 8f),
    floatArrayOf(0f, 0f, 9.81f, 0f, 0f, 9.81f), null,
    9007199254740993L, 4294967295L, 9007199254740997L,
    booleanArrayOf(false, true), booleanArrayOf(true, true, false, true), 80f,
)

class ProtocolTest {
    @Test fun `preserves row order units gaps and exact long counters`() {
        val f = fixture()
        val hello = Json.parseToJsonElement(Protocol.hello("s", 2, "d", "HALO", "HALO_V3", f)).jsonObject
        val stream = hello.getValue("stream").jsonObject
        assertEquals("sample_major", stream.getValue("layout").jsonPrimitive.content)
        assertEquals("uV", stream.getValue("eeg_unit").jsonPrimitive.content)
        assertEquals(f.channels, stream.getValue("channels").jsonArray.map { it.jsonPrimitive.content })
        assertFalse(stream.getValue("has_gyro").jsonPrimitive.boolean)
        val data = Json.parseToJsonElement(Protocol.samples("s", 0, f, 4, 1)).jsonObject
        assertEquals(f.eeg.toList(), data.getValue("eeg").jsonArray.map { it.jsonPrimitive.float })
        assertEquals("9007199254740993", data.getValue("first_sample_index").jsonPrimitive.content)
        assertTrue(data.getValue("host_time_ns").jsonPrimitive.isString)
        assertEquals(JsonNull, data["gyro"])
        assertEquals(listOf(false, true), data.getValue("is_dummy").jsonArray.map { it.jsonPrimitive.boolean })
    }
    @Test fun `rejects mismatched channel or sensor dimensions and nonfinite signal`() {
        for (make in listOf<() -> SignalFrame>(
            { fixture().copy(eeg = floatArrayOf(1f)) },
            { fixture().copy(accel = floatArrayOf(1f, 2f, 3f)) },
            { fixture().copy(dummy = booleanArrayOf(false)) },
            { fixture().copy(eeg = FloatArray(8) { Float.NaN }) },
        )) assertThrows(IllegalArgumentException::class.java) { make() }
    }
    @Test fun `unknown battery is null instead of invalid JSON`() {
        val data = Json.parseToJsonElement(Protocol.samples("s", 0, fixture().copy(battery = Float.NaN), 0, 0)).jsonObject
        assertEquals(JsonNull, data["battery_pct"])
    }
}
