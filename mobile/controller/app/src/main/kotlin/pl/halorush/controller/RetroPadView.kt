package pl.halorush.controller

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.LayerDrawable
import android.graphics.drawable.StateListDrawable
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.widget.Button
import android.widget.FrameLayout

/** Full-size gamepad: native, accessible controls, one event per tap. */
class RetroPadView(context: Context, onPress: (String) -> Unit) : FrameLayout(context) {
    private val keys = linkedMapOf<String, Button>()
    private fun dp(n: Int) = (n * resources.displayMetrics.density).toInt()
    private val cream = Color.rgb(232, 225, 208)
    private val hub = View(context)
    private val pivot = View(context)

    init {
        background = shape(Color.rgb(24, 30, 30), 14).apply { setStroke(dp(5), Color.rgb(71, 81, 83)) }
        setPadding(0, 0, 0, 0)
        hub.background = shape(Color.rgb(14, 18, 18), 0)
        pivot.background = shape(Color.rgb(8, 12, 12), 100)
        addView(hub); addView(pivot)
        val labels = linkedMapOf("up" to "▲", "left" to "◀", "right" to "▶", "down" to "▼",
            "a" to "A", "b" to "B", "x" to "X", "start" to "START", "select" to "SELECT")
        labels.forEach { (key, label) ->
            val action = key in setOf("a", "b", "x")
            val menu = key in setOf("select", "start")
            val button = Button(context).apply {
                text = label; textSize = if (menu) 14f else 26f
                typeface = Typeface.create("monospace", Typeface.BOLD)
                contentDescription = when (key) {
                    "up" -> "W górę"; "down" -> "W dół"; "left" -> "W lewo"; "right" -> "W prawo"; else -> label
                }
                isAllCaps = false; setTextColor(if (menu) Color.rgb(255, 57, 83) else cream); gravity = Gravity.CENTER
                minWidth = 0; minimumWidth = 0; minHeight = 0; minimumHeight = 0
                setPadding(0, 0, 0, 0); backgroundTintList = null
                background = StateListDrawable().apply {
                    addState(intArrayOf(android.R.attr.state_pressed),
                        if (action) shape(if (key == "x") Color.rgb(94, 111, 112) else Color.rgb(239, 30, 64), 100)
                        else shape(Color.rgb(64, 76, 76), 6))
                    addState(intArrayOf(), when {
                        action -> LayerDrawable(arrayOf(
                            shape(if (key == "x") Color.rgb(20, 26, 27) else Color.rgb(116, 0, 27), 100),
                            shape(if (key == "x") Color.rgb(48, 58, 61) else Color.rgb(193, 0, 39), 100),
                        )).apply { setLayerInset(1, 0, 0, 0, dp(6)) }
                        menu -> shape(Color.rgb(14, 18, 18), 8).apply { setStroke(dp(2), Color.rgb(65, 76, 78)) }
                        else -> shape(Color.rgb(14, 18, 18), 5)
                    })
                }
                setOnClickListener { performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); onPress(key) }
            }
            keys[key] = button
            addView(button)
        }
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
            val dot = unit / 2
            bounds(pivot, x + unit + (unit - dot) / 2, y + unit + (unit - dot) / 2, dot, dot)
            place("up", x + unit, y, unit); place("left", x, y + unit, unit)
            place("right", x + 2 * unit, y + unit, unit); place("down", x + unit, y + 2 * unit, unit)
        }
        when {
            width >= dp(480) && width > height -> {
                val unit = minOf(dp(96), (width * .10f).toInt(), (height * .27f).toInt()).coerceAtLeast(dp(48))
                cross(maxOf(dp(16), (width * .19f).toInt() - 3 * unit / 2), (height - 3 * unit) / 2, unit)
                val menuW = (width * .17f).toInt().coerceIn(dp(80), dp(128))
                val menuH = (height * .18f).toInt().coerceIn(dp(48), dp(58))
                val menuX = width / 2 - menuW / 2
                place("start", menuX, height / 2 - menuH - dp(12), menuW, menuH)
                place("select", menuX, height / 2 + dp(12), menuW, menuH)
                val diameter = minOf(dp(96), (height * .30f).toInt(), (width * .14f).toInt()).coerceAtLeast(dp(48))
                val rightX = width - diameter - dp(20)
                place("a", rightX, (height * .24f).toInt() - diameter / 2, diameter)
                place("b", rightX, (height * .76f).toInt() - diameter / 2, diameter)
                place("x", rightX - diameter - dp(14), (height - diameter) / 2, diameter)
            }
            height < dp(320) -> {
                // Small split-screen windows still retain 48 dp touch targets.
                cross(dp(12), dp(12), dp(48))
                place("a", width - dp(60), dp(12), dp(48))
                place("b", width - dp(60), dp(72), dp(48))
                place("x", width - dp(116), dp(42), dp(48))
                place("start", width / 2 - dp(88), height - dp(60), dp(80), dp(48))
                place("select", width / 2 + dp(8), height - dp(60), dp(80), dp(48))
            }
            else -> {
                val unit = minOf(dp(88), (width * .20f).toInt(), (height * .16f).toInt()).coerceAtLeast(dp(48))
                val top = dp(20)
                cross((width - 3 * unit) / 2, top, unit)
                val diameter = minOf(dp(96), (width - dp(64)) / 3, (height * .18f).toInt()).coerceAtLeast(dp(48))
                val actionY = maxOf(top + 3 * unit + dp(20), (height * .57f).toInt() - diameter / 2)
                place("x", dp(20), actionY, diameter)
                place("b", (width - diameter) / 2, actionY, diameter)
                place("a", width - dp(20) - diameter, actionY, diameter)
                place("start", width / 2 - dp(100), height - dp(68), dp(92), dp(48))
                place("select", width / 2 + dp(8), height - dp(68), dp(92), dp(48))
            }
        }
        super.onMeasure(MeasureSpec.makeMeasureSpec(width, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(height, MeasureSpec.EXACTLY))
    }

    private fun shape(color: Int, radius: Int) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
}
