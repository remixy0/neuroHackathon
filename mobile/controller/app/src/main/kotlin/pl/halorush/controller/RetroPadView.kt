package pl.halorush.controller

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.widget.Button
import android.widget.FrameLayout

/**
 * Full-size gamepad: native, accessible controls, one event per tap.
 *
 * Laid out like the Arcade web pad (`arcade/server/pad.html`): cross on top, START over SELECT, X next to
 * A over B; landscape: cross | START/SELECT | X A/B. Skin: a soft dark panel, rounded cross, indigo A,
 * coral B - the buttons the games use most stand out.
 */
class RetroPadView(context: Context, onPress: (String) -> Unit) : FrameLayout(context) {
    private val keys = linkedMapOf<String, Button>()
    private fun dp(n: Int) = (n * resources.displayMetrics.density).toInt()
    private val hub = View(context)
    private val dimple = View(context)

    init {
        background = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(PANEL_TOP, PANEL_BOTTOM)).apply {
            cornerRadius = dp(28).toFloat(); setStroke(dp(1), PANEL_LINE)
        }
        hub.background = GradientDrawable().apply { setColor(DPAD) }
        dimple.background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(DIMPLE) }
        addView(hub); addView(dimple)
        val labels = linkedMapOf("up" to "▲", "left" to "◀", "right" to "▶", "down" to "▼",
            "a" to "A", "b" to "B", "x" to "X", "start" to "START", "select" to "SELECT")
        labels.forEach { (key, label) ->
            val round = key in setOf("a", "b", "x")
            val menu = key in setOf("select", "start")
            val button = Button(context).apply {
                text = label
                textSize = if (menu) 13f else 24f
                typeface = Typeface.create(if (menu) "sans-serif-medium" else "sans-serif-condensed", Typeface.BOLD)
                if (menu) letterSpacing = 0.06f
                contentDescription = when (key) {
                    "up" -> "Up"; "down" -> "Down"; "left" -> "Left"; "right" -> "Right"; else -> label
                }
                isAllCaps = false; gravity = Gravity.CENTER; stateListAnimator = null
                minWidth = 0; minimumWidth = 0; minHeight = 0; minimumHeight = 0
                setPadding(0, 0, 0, 0); backgroundTintList = null
                setTextColor(when {
                    round -> ColorStateList.valueOf(LABEL)
                    menu -> ColorStateList(arrayOf(intArrayOf(android.R.attr.state_pressed), intArrayOf()), intArrayOf(LABEL, MENU_TEXT))
                    else -> ColorStateList(arrayOf(intArrayOf(android.R.attr.state_pressed), intArrayOf()), intArrayOf(LABEL, GLYPH))
                })
                background = when {
                    round -> RoundKey(when (key) { "a" -> WAVE; "b" -> SPARK; else -> X_KEY },
                        when (key) { "a" -> WAVE_ON; "b" -> SPARK_ON; else -> X_KEY_ON }, resources.displayMetrics.density)
                    menu -> pressable(GradientDrawable().apply { setColor(DPAD); cornerRadius = dp(999).toFloat() },
                        GradientDrawable().apply { setColor(DPAD_ON); cornerRadius = dp(999).toFloat() })
                    else -> pressable(arm(key, DPAD), arm(key, DPAD_ON))
                }
                setOnClickListener { performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); onPress(key) }
            }
            keys[key] = button
            addView(button)
        }
    }

    /** One arm of the cross: rounded only on its outer end, flush with the centre square. */
    private fun arm(key: String, color: Int) = GradientDrawable().apply {
        setColor(color)
        val r = dp(14).toFloat()
        cornerRadii = when (key) {
            "up" -> floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f)
            "down" -> floatArrayOf(0f, 0f, 0f, 0f, r, r, r, r)
            "left" -> floatArrayOf(r, r, 0f, 0f, 0f, 0f, r, r)
            else -> floatArrayOf(0f, 0f, r, r, r, r, 0f, 0f)
        }
    }

    private fun pressable(normal: Drawable, pressed: Drawable) = StateListDrawable().apply {
        addState(intArrayOf(android.R.attr.state_pressed), pressed)
        addState(intArrayOf(), normal)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val width = MeasureSpec.getSize(widthMeasureSpec)
        val desiredHeight = dp(if (width >= dp(480)) 320 else 540)
        val height = resolveSize(desiredHeight, heightMeasureSpec)
        fun bounds(view: View, x: Int, y: Int, w: Int, h: Int) {
            val old = view.layoutParams as? LayoutParams
            if (old?.width != w || old.height != h || old.leftMargin != x || old.topMargin != y)
                view.layoutParams = LayoutParams(w, h).apply { leftMargin = x; topMargin = y }
        }
        fun place(key: String, x: Int, y: Int, w: Int, h: Int = w) = bounds(keys.getValue(key), x, y, w, h)
        fun cross(x: Int, y: Int, unit: Int) {
            bounds(hub, x + unit, y + unit, unit, unit)
            val dot = unit * 46 / 100
            bounds(dimple, x + unit + (unit - dot) / 2, y + unit + (unit - dot) / 2, dot, dot)
            place("up", x + unit, y, unit); place("left", x, y + unit, unit)
            place("right", x + 2 * unit, y + unit, unit); place("down", x + unit, y + 2 * unit, unit)
            keys.values.take(4).forEach { it.setTextSize(TypedValue.COMPLEX_UNIT_PX, unit * 0.4f) }
        }
        fun roundLabels(size: Int) = listOf("a", "b", "x").forEach {
            keys.getValue(it).setTextSize(TypedValue.COMPLEX_UNIT_PX, size * 0.32f)
        }
        val min = dp(48)
        val inset = dp(18)                                  // panel padding
        when {
            width >= dp(480) && width > height -> {
                // cross | START over SELECT | X, A over B - the whole row centred
                val innerH = height - 2 * inset
                val unit = minOf(innerH / 3, width * 13 / 100, dp(130)).coerceAtLeast(min)
                val key = minOf((innerH - dp(10)) / 2, width * 15 / 100, dp(140)).coerceAtLeast(min)
                val sysW = minOf(width * 14 / 100, dp(120)).coerceAtLeast(dp(72))
                val sysH = dp(48)
                val gap = (width * 4 / 100).coerceIn(dp(12), dp(48))
                val gapAB = minOf(width * 4 / 100, dp(20))
                val total = 3 * unit + gap + sysW + gap + key + gapAB + key
                var x = (width - total) / 2
                cross(x, (height - 3 * unit) / 2, unit)
                x += 3 * unit + gap
                place("start", x, height / 2 - sysH - dp(7), sysW, sysH)
                place("select", x, height / 2 + dp(7), sysW, sysH)
                x += sysW + gap
                place("x", x, (height - key) / 2, key)
                x += key + gapAB
                val stack = 2 * key + dp(10)
                place("a", x, (height - stack) / 2, key)
                place("b", x, (height - stack) / 2 + key + dp(10), key)
                roundLabels(key)
            }
            height < dp(320) -> {
                // Small split-screen windows still retain 48 dp touch targets.
                cross(dp(12), dp(12), min)
                place("a", width - dp(60), dp(12), min)
                place("b", width - dp(60), dp(72), min)
                place("x", width - dp(116), dp(42), min)
                place("start", width / 2 - dp(88), height - dp(60), dp(80), min)
                place("select", width / 2 + dp(8), height - dp(60), dp(80), min)
                roundLabels(min)
            }
            else -> {
                // cross on top; below: START over SELECT | X, A over B
                val innerW = width - 2 * inset
                val innerH = height - 2 * inset
                val sysW = minOf(width * 26 / 100, dp(120)).coerceAtLeast(dp(72))
                val sysH = dp(48)
                val gapV = (height * 4 / 100).coerceIn(dp(14), dp(32))
                val gapH = (width * 5 / 100).coerceIn(dp(12), dp(28))
                val gapAB = minOf(width * 4 / 100, dp(20))
                val key = minOf(width * 28 / 100, (innerH - dp(40)) / 5, dp(130),
                    (innerW - sysW - gapH - gapAB) / 2).coerceAtLeast(min)
                val stack = 2 * key + dp(10)
                val unit = minOf(width * 31 / 100, (innerH - stack - gapV) / 3, dp(130)).coerceAtLeast(min)
                val top = (height - (3 * unit + gapV + stack)) / 2
                cross((width - 3 * unit) / 2, top, unit)
                val rowY = top + 3 * unit + gapV
                val rowW = sysW + gapH + key + gapAB + key
                var x = (width - rowW) / 2
                place("start", x, rowY + stack / 2 - sysH - dp(7), sysW, sysH)
                place("select", x, rowY + stack / 2 + dp(7), sysW, sysH)
                x += sysW + gapH
                place("x", x, rowY + (stack - key) / 2, key)
                x += key + gapAB
                place("a", x, rowY, key)
                place("b", x, rowY + key + dp(10), key)
                roundLabels(key)
            }
        }
        super.onMeasure(MeasureSpec.makeMeasureSpec(width, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(height, MeasureSpec.EXACTLY))
    }

    /** A/B/X: a round button with a darker rim under it (pressed: lighter and pushed down onto the rim). */
    private class RoundKey(private val face: Int, private val faceOn: Int, private val density: Float) : Drawable() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private var pressed = false
        override fun isStateful() = true
        override fun onStateChange(state: IntArray): Boolean {
            val now = android.R.attr.state_pressed in state
            if (now == pressed) return false
            pressed = now; invalidateSelf(); return true
        }
        override fun draw(canvas: Canvas) {
            val b = bounds
            val cx = b.exactCenterX(); val cy = b.exactCenterY()
            val radius = minOf(b.width(), b.height()) * 0.46f
            val drop = 4 * density
            paint.color = RIM                               // rim under the button: it stands out of the panel
            canvas.drawCircle(cx, cy + drop / 2, radius - drop / 2, paint)
            paint.color = if (pressed) faceOn else face
            canvas.drawCircle(cx, if (pressed) cy + drop / 2 else cy - drop / 2, radius - drop / 2, paint)
        }
        override fun setAlpha(alpha: Int) { paint.alpha = alpha }
        override fun setColorFilter(colorFilter: ColorFilter?) { paint.colorFilter = colorFilter }
        @Deprecated("Deprecated in Java")
        override fun getOpacity() = PixelFormat.TRANSLUCENT
    }

    private companion object {
        val PANEL_TOP = Color.rgb(0x1c, 0x20, 0x3f)
        val PANEL_BOTTOM = Color.rgb(0x14, 0x17, 0x2f)
        val PANEL_LINE = Color.rgb(0x2c, 0x31, 0x57)
        val DPAD = Color.rgb(0x2a, 0x2f, 0x58)
        val DPAD_ON = Color.rgb(0x5b, 0x4c, 0xf5)
        val DIMPLE = Color.rgb(0x20, 0x24, 0x47)
        val GLYPH = Color.rgb(0x9d, 0xa2, 0xd6)
        val MENU_TEXT = Color.rgb(0xc9, 0xcc, 0xeb)
        val WAVE = Color.rgb(0x5b, 0x4c, 0xf5)
        val WAVE_ON = Color.rgb(0x7d, 0x70, 0xff)
        val SPARK = Color.rgb(0xff, 0x5f, 0x57)
        val SPARK_ON = Color.rgb(0xff, 0x82, 0x7b)
        val X_KEY = Color.rgb(0x3a, 0x40, 0x70)
        val X_KEY_ON = Color.rgb(0x52, 0x59, 0x8c)
        val RIM = Color.argb(0xb0, 0x08, 0x0a, 0x18)
        val LABEL = Color.WHITE
    }
}
