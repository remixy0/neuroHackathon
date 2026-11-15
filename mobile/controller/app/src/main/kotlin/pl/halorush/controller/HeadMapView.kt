package pl.halorush.controller

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.view.View

/**
 * The head seen from above (nose at the top) with HALO's four electrodes where they sit on it: Fp1/Fp2 on the
 * forehead, O1/O2 at the back of the head, 1 = left, 2 = right. Green = touches the skin, coral ring = does not,
 * grey = no data yet. Lets the player see which part of the headband to adjust.
 */
class HeadMapView(context: Context) : View(context) {
    private class Spot(val name: String, val x: Float, val y: Float)

    private val spots = listOf(Spot("Fp1", -0.34f, -0.72f), Spot("Fp2", 0.34f, -0.72f),
        Spot("O1", -0.34f, 0.74f), Spot("O2", 0.34f, 0.74f))
    private val density = resources.displayMetrics.density
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val label = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER; typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD)
    }

    /** Electrode name -> touches the skin; null = no data from the headband yet. */
    var contacts: Map<String, Boolean>? = null
        set(value) {
            field = value
            contentDescription = describe(value)
            invalidate()
        }

    init { contentDescription = describe(null) }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val size = resolveSize((240 * density).toInt(), widthMeasureSpec)
        setMeasuredDimension(size, resolveSize(size, heightMeasureSpec))
    }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f + 4 * density
        val r = minOf(width, height) / 2f - 20 * density
        val line = 3 * density
        // ears and nose first, so the head outline covers their inner ends
        stroke.strokeWidth = line; stroke.color = OUTLINE
        val ear = 10 * density
        canvas.drawArc(RectF(cx - r - ear, cy - 2.2f * ear, cx - r + ear, cy + 2.2f * ear), 90f, 180f, false, stroke)
        canvas.drawArc(RectF(cx + r - ear, cy - 2.2f * ear, cx + r + ear, cy + 2.2f * ear), 270f, 180f, false, stroke)
        val nose = Path().apply {
            moveTo(cx - 11 * density, cy - r + 3 * density)
            lineTo(cx, cy - r - 15 * density)
            lineTo(cx + 11 * density, cy - r + 3 * density)
        }
        fill.color = HEAD
        canvas.drawPath(nose, fill)
        canvas.drawPath(nose, stroke)
        canvas.drawCircle(cx, cy, r, fill)
        canvas.drawCircle(cx, cy, r, stroke)
        // faint guides: centre line front to back and the band's ring
        stroke.strokeWidth = 1.5f * density; stroke.color = GUIDE
        canvas.drawLine(cx, cy - r + line, cx, cy + r - line, stroke)
        canvas.drawCircle(cx, cy, r * 0.79f, stroke)

        val known = contacts
        val dot = r * 0.17f
        label.textSize = dot * 0.72f
        for (s in spots) {
            val x = cx + s.x * r
            val y = cy + s.y * r
            when (known?.get(s.name)) {
                true -> {
                    fill.color = GOOD_GLOW; canvas.drawCircle(x, y, dot * 1.55f, fill)
                    fill.color = GOOD; canvas.drawCircle(x, y, dot, fill)
                    label.color = GOOD_INK
                }
                false -> {
                    fill.color = HEAD; canvas.drawCircle(x, y, dot, fill)
                    stroke.strokeWidth = 3 * density; stroke.color = BAD
                    canvas.drawCircle(x, y, dot - 1.5f * density, stroke)
                    label.color = BAD
                }
                null -> {
                    fill.color = UNKNOWN; canvas.drawCircle(x, y, dot, fill)
                    label.color = UNKNOWN_INK
                }
            }
            canvas.drawText(s.name, x, y - (label.descent() + label.ascent()) / 2, label)
        }
    }

    companion object {
        private val HEAD = Color.rgb(0x1a, 0x1e, 0x3a)
        private val OUTLINE = Color.rgb(0x3a, 0x40, 0x70)
        private val GUIDE = Color.rgb(0x26, 0x2b, 0x4e)
        private val GOOD = Color.rgb(0x22, 0xc5, 0x8b)
        private val GOOD_GLOW = Color.argb(0x40, 0x22, 0xc5, 0x8b)
        private val GOOD_INK = Color.rgb(0x07, 0x2e, 0x21)
        private val BAD = Color.rgb(0xff, 0x5f, 0x57)
        private val UNKNOWN = Color.rgb(0x2c, 0x31, 0x57)
        private val UNKNOWN_INK = Color.rgb(0x9d, 0xa2, 0xc9)

        /** Where on the head an electrode sits, in words: "on the forehead, left". */
        fun place(name: String): String {
            val where = if (name.startsWith("Fp")) "on the forehead" else "at the back of the head"
            val side = if (name.endsWith("1")) "left" else "right"
            return "$where, $side"
        }

        /** One sentence for the player (and screen readers) about the electrodes. */
        fun describe(contacts: Map<String, Boolean>?): String {
            if (contacts == null) return "Waiting for data from the headband."
            val bad = contacts.filterValues { !it }.keys.toList()
            return when (bad.size) {
                0 -> "All electrodes are in contact."
                1 -> "${bad[0]} is not touching the skin. Adjust the headband ${place(bad[0])}."
                contacts.size -> "No electrode is touching the skin. Put the headband on more tightly."
                else -> "${bad.joinToString(" and ")} are not touching the skin. Adjust the headband: " +
                    bad.joinToString("; ") { "${it} ${place(it)}" } + "."
            }
        }
    }
}
