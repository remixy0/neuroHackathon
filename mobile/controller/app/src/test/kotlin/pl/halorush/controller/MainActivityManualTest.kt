package pl.halorush.controller

import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.RadioButton
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.annotation.LooperMode
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@LooperMode(LooperMode.Mode.PAUSED)
class MainActivityManualTest {
    private fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
        (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    private fun until(condition: () -> Boolean) {
        val deadline = System.nanoTime() + 5_000_000_000L
        while (!condition() && System.nanoTime() < deadline) {
            shadowOf(Looper.getMainLooper()).idle()
            Thread.sleep(15)
        }
        assertTrue("UI / socket did not reach the expected state", condition())
    }

    @Test fun `manual flow skips HALO switches player and stops from the UI`() {
        val messages = CopyOnWriteArrayList<JsonObject>()
        val server = MockWebServer()
        repeat(2) {
            server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
                override fun onMessage(ws: WebSocket, text: String) {
                    val msg = Json.parseToJsonElement(text).jsonObject
                    messages.add(msg)
                    val type = msg.getValue("type").jsonPrimitive.content
                    if (type == "hello" || type == "manual") ws.send(buildJsonObject {
                        put("type", if (type == "hello") "ready" else "ack")
                        put("version", 1); put("session_id", msg.getValue("session_id"))
                        if (type == "hello") { put("mode", "manual"); put("player", msg.getValue("player")) }
                        else put("seq", msg.getValue("seq"))
                    }.toString())
                }
                override fun onClosing(ws: WebSocket, code: Int, reason: String) { ws.close(code, reason) }
            }))
        }
        val owner = Robolectric.buildActivity(MainActivity::class.java).setup()
        val activity = owner.get()
        fun all() = views(activity.window.decorView)
        fun click(label: String) = all().filterIsInstance<Button>().first { it.text.toString() == label || it.contentDescription?.toString() == label }.performClick()
        try {
            all().filterIsInstance<EditText>().first().setText(server.url("/ws/controller").toString().replaceFirst("http", "ws"))
            activity.findViewById<RadioButton>(R.id.mode_manual).performClick()
            click("Dalej")
            until { all().any { it is RetroPadView } }
            @Suppress("DEPRECATION")
            assertTrue(activity.window.decorView.systemUiVisibility and View.SYSTEM_UI_FLAG_FULLSCREEN != 0)
            assertFalse(all().filterIsInstance<Button>().any { it.text.toString() == "Szukaj HALO" })
            click("A")
            until { messages.any { it["type"]?.jsonPrimitive?.content == "manual" } }
            assertEquals("a", messages.last().getValue("button").jsonPrimitive.content)

            fun preview(width: Int, height: Int, name: String) {
                val decor = activity.window.decorView
                decor.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
                    View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY))
                decor.layout(0, 0, width, height)
                assertFalse(all().any { it is android.widget.ScrollView })
                val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                decor.draw(Canvas(bitmap))
                val file = File(System.getProperty("halo.previewDir"), name)
                requireNotNull(file.parentFile).mkdirs()
                file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            }
            preview(400, 800, "manual-portrait.png")
            val firstSession = messages.first().getValue("session_id")
            val landscape = Configuration(activity.resources.configuration).apply {
                orientation = Configuration.ORIENTATION_LANDSCAPE
                screenWidthDp = 800; screenHeightDp = 400; smallestScreenWidthDp = 400
            }
            owner.configurationChange(landscape)
            shadowOf(Looper.getMainLooper()).idle()
            assertSame("Rotation must not recreate the Activity", activity, owner.get())
            assertTrue(all().any { it is RetroPadView })
            preview(800, 400, "manual-landscape.png")
            click("X")
            until { messages.count { it["type"]?.jsonPrimitive?.content == "manual" } == 2 }
            val portrait = Configuration(activity.resources.configuration).apply {
                orientation = Configuration.ORIENTATION_PORTRAIT
                screenWidthDp = 400; screenHeightDp = 800; smallestScreenWidthDp = 400
            }
            owner.configurationChange(portrait)
            shadowOf(Looper.getMainLooper()).idle()
            assertSame(activity, owner.get())
            click("B")
            until { messages.count { it["type"]?.jsonPrimitive?.content == "manual" } == 3 }
            assertEquals(1, messages.count { it["type"]?.jsonPrimitive?.content == "hello" })
            assertEquals(0, messages.count { it["type"]?.jsonPrimitive?.content == "stop" })
            val beforeSwitch = messages.filter { it["type"]?.jsonPrimitive?.content == "manual" }
            assertTrue(beforeSwitch.all { it["session_id"] == firstSession })
            assertEquals(listOf(0, 1, 2), beforeSwitch.map { it.getValue("seq").jsonPrimitive.int })

            click("GRACZ 2")
            until { messages.count { it["type"]?.jsonPrimitive?.content == "hello" } == 2 && all().any { it is RetroPadView } }
            click("B")
            until { messages.count { it["type"]?.jsonPrimitive?.content == "manual" } == 4 }
            val events = messages.filter { it["type"]?.jsonPrimitive?.content == "manual" }
            assertEquals(listOf(1, 1, 1, 2), events.map { it.getValue("player").jsonPrimitive.int })
            assertNotEquals(events[0]["session_id"], events[3]["session_id"])
            assertEquals(listOf(0, 1, 2, 0), events.map { it.getValue("seq").jsonPrimitive.int })
            click("Zakończ / zmień tryb")
            until { all().filterIsInstance<Button>().any { it.text.toString() == "Dalej" } }
            @Suppress("DEPRECATION")
            assertEquals(0, activity.window.decorView.systemUiVisibility and View.SYSTEM_UI_FLAG_FULLSCREEN)
            until { messages.count { it["type"]?.jsonPrimitive?.content == "stop" } == 2 }
        } finally { owner.pause().stop().destroy(); server.close() }
    }
}
