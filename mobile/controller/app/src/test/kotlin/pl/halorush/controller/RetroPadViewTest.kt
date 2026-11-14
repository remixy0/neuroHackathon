package pl.halorush.controller

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Rect
import android.view.ContextThemeWrapper
import android.view.View
import android.widget.Button
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class RetroPadViewTest {
    @Test fun `all buttons stay accessible and distinct on narrow portrait and landscape pads`() {
        for ((width, height) in listOf(280 to 440, 312 to 600, 360 to 560, 400 to 680, 640 to 220, 800 to 300, 1024 to 500, 280 to 220)) {
            val presses = mutableListOf<String>()
            val context = ContextThemeWrapper(RuntimeEnvironment.getApplication(), R.style.AppTheme)
            val pad = RetroPadView(context) { presses.add(it) }
            pad.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY))
            pad.layout(0, 0, pad.measuredWidth, pad.measuredHeight)
            val buttons = (0 until pad.childCount).map { pad.getChildAt(it) }.filterIsInstance<Button>()
            assertEquals(9, buttons.size)
            assertEquals(height, pad.height)
            val actions = buttons.filter { it.text.toString() in setOf("A", "B", "X") }
            assertEquals(3, actions.size)
            assertEquals(1, actions.map { it.width to it.height }.toSet().size)
            assertTrue(actions.all { it.width == it.height })
            for (button in buttons) {
                assertTrue(button.width >= 48 && button.height >= 48)
                assertTrue(button.left >= 0 && button.top >= 0 && button.right <= pad.width && button.bottom <= pad.height)
                assertTrue(button.contentDescription.isNotBlank())
                button.performClick()
            }
            for ((i, a) in buttons.withIndex()) for (b in buttons.drop(i + 1)) {
                assertFalse("Overlapping controls at $width: ${a.text} / ${b.text}",
                    Rect.intersects(Rect(a.left, a.top, a.right, a.bottom), Rect(b.left, b.top, b.right, b.bottom)))
            }
            assertEquals(Protocol.MANUAL_BUTTONS, presses.toSet())
            assertEquals(9, presses.size)
            val bitmap = Bitmap.createBitmap(pad.width, pad.height, Bitmap.Config.ARGB_8888)
            pad.draw(Canvas(bitmap))
            val output = File(System.getProperty("halo.previewDir"), "pad-${width}x$height.png")
            requireNotNull(output.parentFile).mkdirs()
            output.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
}
