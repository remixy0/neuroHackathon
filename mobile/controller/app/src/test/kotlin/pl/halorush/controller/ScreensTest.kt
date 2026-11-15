package pl.halorush.controller

import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.RadioButton
import android.widget.TextView
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/** Setup and in-game screens: shorthand server address, headset list, live status. Writes PNG previews. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ScreensTest {
    private fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
        (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    private fun preview(activity: MainActivity, name: String, width: Int = 400, height: Int = 860) {
        val decor = activity.window.decorView
        decor.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
            View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY))
        decor.layout(0, 0, width, height)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        decor.draw(Canvas(bitmap))
        val file = File(System.getProperty("halo.previewDir"), name)
        requireNotNull(file.parentFile).mkdirs()
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    /** Private screen switch, only to render the in-game screens without a headset. */
    private fun showScreen(activity: MainActivity, name: String) {
        val screen = Class.forName("pl.halorush.controller.MainActivity\$Screen")
        val value = screen.enumConstants!!.first { (it as Enum<*>).name == name }
        MainActivity::class.java.getDeclaredMethod("show", screen).apply { isAccessible = true }.invoke(activity, value)
    }

    private fun set(activity: MainActivity, field: String, value: Any?) =
        MainActivity::class.java.getDeclaredField(field).apply { isAccessible = true }.set(activity, value)

    @Test fun `bare IP is enough and the headset screen follows`() {
        val owner = Robolectric.buildActivity(MainActivity::class.java).setup()
        val activity = owner.get()
        fun all() = views(activity.window.decorView)
        fun texts() = all().filterIsInstance<TextView>().map { it.text.toString() }
        try {
            val address = all().filterIsInstance<EditText>().first()
            address.setText("172.20.10.2")
            assertTrue(texts().contains("✓ Will connect to ws://172.20.10.2:8000/ws/controller"))
            // token only when the server needs one
            val token = all().filterIsInstance<EditText>()[1]
            assertEquals(View.GONE, token.visibility)
            preview(activity, "screen-server.png", height = 1000)
            all().filterIsInstance<Button>().first { it.text.toString() == "Server needs a token?" }.performClick()
            assertEquals(View.VISIBLE, token.visibility)
            address.setText("172.20 .10.2")
            assertTrue(texts().any { it.startsWith("That is not an address") })
            address.setText("172.20.10.2")
            activity.findViewById<RadioButton>(2).performClick()
            activity.findViewById<RadioButton>(R.id.mode_halo).performClick()
            all().filterIsInstance<Button>().first { it.text.toString() == "Next" }.performClick()
            shadowOf(Looper.getMainLooper()).idle()
            assertEquals("ws://172.20.10.2:8000/ws/controller",
                activity.getSharedPreferences("controller", 0).getString("endpoint", null))
            assertTrue(all().filterIsInstance<Button>().any { it.text.toString() == "Search for HALO" })
            assertTrue(texts().contains("Player 2, server 172.20.10.2:8000"))
            preview(activity, "screen-device.png")
        } finally { owner.pause().stop().destroy() }
    }

    @Test fun `in-game screen says where on the head an electrode lost contact`() {
        val owner = Robolectric.buildActivity(MainActivity::class.java).setup()
        val activity = owner.get()
        fun all() = views(activity.window.decorView)
        fun texts() = all().filterIsInstance<TextView>().map { it.text.toString() }
        try {
            set(activity, "serverUrl", "ws://172.20.10.2:8000/ws/controller")
            set(activity, "lastDirection", "left")
            set(activity, "latestStats", StreamStats(41_250, 12, 3, 87f,
                listOf("O1" to true, "O2" to true, "Fp2" to true, "Fp1" to false), 250))
            showScreen(activity, "STATUS")
            assertTrue(texts().contains("Fp1 is not touching the skin. Adjust the headband on the forehead, left."))
            assertTrue(texts().contains("Left"))
            assertTrue(texts().any { it.startsWith("Battery 87%") })
            val map = all().filterIsInstance<HeadMapView>().single()
            assertEquals("Fp1 is not touching the skin. Adjust the headband on the forehead, left.", map.contentDescription)
            preview(activity, "screen-status.png", height = 900)
            set(activity, "latestStats", StreamStats(41_250, 0, 0, 87f,
                listOf("O1" to true, "O2" to true, "Fp2" to true, "Fp1" to true), 250))
            showScreen(activity, "STATUS")
            assertTrue(texts().contains("All electrodes are in contact."))
            preview(activity, "screen-status-ok.png", height = 900)
            set(activity, "connectionError", "Backend closed the connection (1001)")
            showScreen(activity, "CONNECTING")
            assertTrue(all().filterIsInstance<Button>().any { it.text.toString() == "Try again" })
            preview(activity, "screen-error.png")
            set(activity, "connectionError", null)
            set(activity, "phase", ConnectionPhase.SERVER)
            showScreen(activity, "CONNECTING")
            preview(activity, "screen-connecting.png")
        } finally { owner.pause().stop().destroy() }
    }

    @Test fun `electrode messages name the place on the head`() {
        assertEquals("Waiting for data from the headband.", HeadMapView.describe(null))
        assertEquals("O2 is not touching the skin. Adjust the headband at the back of the head, right.",
            HeadMapView.describe(mapOf("Fp1" to true, "Fp2" to true, "O1" to true, "O2" to false)))
        assertEquals("No electrode is touching the skin. Put the headband on more tightly.",
            HeadMapView.describe(mapOf("Fp1" to false, "Fp2" to false, "O1" to false, "O2" to false)))
        assertEquals("Fp1 and O1 are not touching the skin. Adjust the headband: Fp1 on the forehead, left; O1 at the back of the head, left.",
            HeadMapView.describe(mapOf("Fp1" to false, "Fp2" to true, "O1" to false, "O2" to true)))
    }
}
