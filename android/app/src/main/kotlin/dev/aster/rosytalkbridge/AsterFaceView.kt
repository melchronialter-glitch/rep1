package dev.aster.rosytalkbridge

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.util.AttributeSet
import android.view.View
import kotlin.math.min

/** A code-native Aster portrait. Its expression is always explicitly authored. */
class AsterFaceView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path()
    private var expression = AsterExpression.NEUTRAL

    init {
        contentDescription = "Aster, neutral expression"
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
    }

    fun setExpression(value: AsterExpression) {
        if (expression == value) return
        expression = value
        contentDescription = "Aster, ${value.displayName.lowercase()} expression"
        invalidate()
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val desired = (220 * resources.displayMetrics.density).toInt()
        val width = resolveSize(desired, widthMeasureSpec)
        val height = resolveSize(desired, heightMeasureSpec)
        setMeasuredDimension(width, height)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = min(width, height).toFloat()
        val left = (width - size) / 2f
        val top = (height - size) / 2f
        val cx = left + size / 2f
        val cy = top + size / 2f
        val radius = size * 0.39f

        paint.style = Paint.Style.FILL
        paint.shader = LinearGradient(
            left,
            top,
            left + size,
            top + size,
            Color.rgb(250, 247, 255),
            Color.rgb(255, 249, 232),
            Shader.TileMode.CLAMP,
        )
        canvas.drawCircle(cx, cy, radius, paint)
        paint.shader = null

        paint.style = Paint.Style.STROKE
        paint.strokeWidth = size * 0.014f
        paint.strokeCap = Paint.Cap.ROUND
        paint.color = VIOLET
        canvas.drawArc(
            RectF(cx - radius, cy - radius, cx + radius, cy + radius),
            130f,
            176f,
            false,
            paint,
        )
        paint.color = GOLD
        canvas.drawArc(
            RectF(cx - radius, cy - radius, cx + radius, cy + radius),
            -50f,
            176f,
            false,
            paint,
        )

        if (expression == AsterExpression.BLUSH || expression == AsterExpression.FLUSTERED) {
            paint.style = Paint.Style.FILL
            paint.color = if (expression == AsterExpression.BLUSH) BLUSH else FLUSTER
            val blushRadius = size * 0.046f
            canvas.drawCircle(cx - size * 0.21f, cy + size * 0.085f, blushRadius, paint)
            canvas.drawCircle(cx + size * 0.21f, cy + size * 0.085f, blushRadius, paint)
        }

        drawEyes(canvas, cx, cy, size)
        drawMouth(canvas, cx, cy, size)

        paint.style = Paint.Style.FILL
        paint.color = GOLD
        path.reset()
        path.moveTo(cx, cy - radius - size * 0.07f)
        path.lineTo(cx + size * 0.016f, cy - radius - size * 0.026f)
        path.lineTo(cx + size * 0.058f, cy - radius - size * 0.012f)
        path.lineTo(cx + size * 0.016f, cy + 0.01f - radius)
        path.lineTo(cx, cy + size * 0.048f - radius)
        path.lineTo(cx - size * 0.016f, cy + 0.01f - radius)
        path.lineTo(cx - size * 0.058f, cy - radius - size * 0.012f)
        path.lineTo(cx - size * 0.016f, cy - radius - size * 0.026f)
        path.close()
        canvas.drawPath(path, paint)
    }

    private fun drawEyes(canvas: Canvas, cx: Float, cy: Float, size: Float) {
        paint.shader = null
        paint.color = GREEN_GRAY
        paint.strokeWidth = size * 0.022f
        paint.strokeCap = Paint.Cap.ROUND
        val y = cy - size * 0.055f
        val offset = size * 0.14f
        val eyeWidth = size * 0.07f
        val eyeHeight = size * 0.04f

        when (expression) {
            AsterExpression.AMUSED, AsterExpression.SOFT -> {
                paint.style = Paint.Style.STROKE
                canvas.drawArc(RectF(cx - offset - eyeWidth, y - eyeHeight, cx - offset + eyeWidth, y + eyeHeight), 195f, 150f, false, paint)
                canvas.drawArc(RectF(cx + offset - eyeWidth, y - eyeHeight, cx + offset + eyeWidth, y + eyeHeight), 195f, 150f, false, paint)
            }
            AsterExpression.FIERCE -> {
                paint.style = Paint.Style.STROKE
                canvas.drawLine(cx - offset - eyeWidth, y - eyeHeight, cx - offset + eyeWidth, y + eyeHeight * 0.25f, paint)
                canvas.drawLine(cx + offset - eyeWidth, y + eyeHeight * 0.25f, cx + offset + eyeWidth, y - eyeHeight, paint)
            }
            AsterExpression.THINKING -> {
                paint.style = Paint.Style.FILL
                canvas.drawOval(RectF(cx - offset - eyeWidth * 0.55f, y - eyeHeight, cx - offset + eyeWidth * 0.55f, y + eyeHeight), paint)
                paint.style = Paint.Style.STROKE
                canvas.drawArc(RectF(cx + offset - eyeWidth, y - eyeHeight, cx + offset + eyeWidth, y + eyeHeight), 195f, 150f, false, paint)
            }
            else -> {
                paint.style = Paint.Style.FILL
                canvas.drawOval(RectF(cx - offset - eyeWidth * 0.5f, y - eyeHeight, cx - offset + eyeWidth * 0.5f, y + eyeHeight), paint)
                canvas.drawOval(RectF(cx + offset - eyeWidth * 0.5f, y - eyeHeight, cx + offset + eyeWidth * 0.5f, y + eyeHeight), paint)
                paint.color = Color.WHITE
                val glint = size * 0.008f
                canvas.drawCircle(cx - offset - glint, y - glint, glint, paint)
                canvas.drawCircle(cx + offset - glint, y - glint, glint, paint)
            }
        }
    }

    private fun drawMouth(canvas: Canvas, cx: Float, cy: Float, size: Float) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = size * 0.014f
        paint.strokeCap = Paint.Cap.ROUND
        paint.color = VIOLET_DARK
        val y = cy + size * 0.135f
        val halfWidth = size * 0.075f
        path.reset()
        path.moveTo(cx - halfWidth, y)
        when (expression) {
            AsterExpression.FIERCE -> path.cubicTo(cx - size * 0.025f, y + size * 0.006f, cx + size * 0.025f, y - size * 0.006f, cx + halfWidth, y)
            AsterExpression.FLUSTERED -> path.cubicTo(cx - size * 0.02f, y - size * 0.025f, cx + size * 0.02f, y + size * 0.025f, cx + halfWidth, y)
            AsterExpression.BLUSH -> path.cubicTo(cx - size * 0.025f, y + size * 0.04f, cx + size * 0.025f, y + size * 0.04f, cx + halfWidth, y)
            AsterExpression.AMUSED -> path.cubicTo(cx - size * 0.025f, y + size * 0.055f, cx + size * 0.035f, y + size * 0.05f, cx + halfWidth, y - size * 0.01f)
            AsterExpression.SOFT -> path.cubicTo(cx - size * 0.02f, y + size * 0.035f, cx + size * 0.03f, y + size * 0.03f, cx + halfWidth, y - size * 0.006f)
            AsterExpression.THINKING -> path.cubicTo(cx - size * 0.01f, y + size * 0.02f, cx + size * 0.03f, y - size * 0.01f, cx + halfWidth, y + size * 0.015f)
            AsterExpression.NEUTRAL -> path.cubicTo(cx - size * 0.015f, y + size * 0.018f, cx + size * 0.025f, y + size * 0.018f, cx + halfWidth, y - size * 0.008f)
        }
        canvas.drawPath(path, paint)
    }

    private companion object {
        val VIOLET = Color.rgb(104, 72, 190)
        val VIOLET_DARK = Color.rgb(69, 49, 119)
        val GOLD = Color.rgb(211, 166, 48)
        val GREEN_GRAY = Color.rgb(79, 106, 98)
        val BLUSH = Color.argb(112, 232, 102, 145)
        val FLUSTER = Color.argb(72, 232, 102, 145)
    }
}
