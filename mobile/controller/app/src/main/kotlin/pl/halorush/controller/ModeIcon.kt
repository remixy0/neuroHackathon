package pl.halorush.controller

import android.graphics.Canvas
import android.graphics.ColorFilter
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.drawable.Drawable

/** Line icons for the two ways of playing: a head wearing the HALO band, and a gamepad. */
class ModeIcon(private val kind: Kind, private val color: Int, private val accent: Int, private val density: Float) : Drawable() {
    enum class Kind { HEADBAND, PAD }

    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 2.4f * density; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
    }
    private val dot = Paint(Paint.ANTI_ALIAS_FLAG)

    override fun getIntrinsicWidth() = (40 * density).toInt()
    override fun getIntrinsicHeight() = (40 * density).toInt()

    override fun draw(canvas: Canvas) {
        val b = bounds
        val s = minOf(b.width(), b.height()).toFloat()
        val cx = b.exactCenterX(); val cy = b.exactCenterY()
        line.color = color
        dot.color = accent
        when (kind) {
            Kind.HEADBAND -> {
                // head from the front, the band across the forehead, three sensors on the band
                val r = s * 0.36f
                val hy = cy + s * 0.02f
                canvas.drawCircle(cx, hy, r, line)
                line.color = accent
                val band = RectF(cx - r, hy - r * 0.62f, cx + r, hy + r * 0.9f)    // the band follows the head's curve
                canvas.drawArc(band, 200f, 140f, false, line)
                val ecx = band.centerX(); val ecy = band.centerY(); val rx = band.width() / 2; val ry = band.height() / 2
                for (deg in listOf(232.0, 270.0, 308.0)) {
                    val a = Math.toRadians(deg)
                    canvas.drawCircle((ecx + rx * kotlin.math.cos(a)).toFloat(), (ecy + ry * kotlin.math.sin(a)).toFloat(), 3f * density, dot)
                }
            }
            Kind.PAD -> {
                val w = s * 0.84f; val h = s * 0.5f
                canvas.drawRoundRect(RectF(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), h * 0.45f, h * 0.45f, line)
                val px = cx - w * 0.22f; val arm = h * 0.22f
                canvas.drawLine(px - arm, cy, px + arm, cy, line)
                canvas.drawLine(px, cy - arm, px, cy + arm, line)
                canvas.drawCircle(cx + w * 0.17f, cy + h * 0.1f, 2.8f * density, dot)
                canvas.drawCircle(cx + w * 0.29f, cy - h * 0.1f, 2.8f * density, dot)
            }
        }
    }

    override fun setAlpha(alpha: Int) { line.alpha = alpha; dot.alpha = alpha }
    override fun setColorFilter(colorFilter: ColorFilter?) { line.colorFilter = colorFilter; dot.colorFilter = colorFilter }
    @Deprecated("Deprecated in Java")
    override fun getOpacity() = PixelFormat.TRANSLUCENT
}
