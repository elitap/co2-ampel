package io.github.elitap.co2ampel.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.github.elitap.co2ampel.R
import io.github.elitap.co2ampel.domain.HistoryPoint
import io.github.elitap.co2ampel.domain.Level
import io.github.elitap.co2ampel.domain.Thresholds
import io.github.elitap.co2ampel.domain.formatDayClock
import io.github.elitap.co2ampel.ui.theme.levelColor
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import kotlin.math.max
import kotlin.math.roundToInt

/** Einfaches Liniendiagramm der Verbrauchsintensität (48 h) mit gestrichelten Ampelgrenzen. */
@Composable
fun HistoryChart(points: List<HistoryPoint>, thresholds: Thresholds, now: Instant) {
    if (points.size < 2) {
        Text(stringResource(R.string.history_empty), style = MaterialTheme.typography.bodyMedium)
        return
    }
    val start = maxOf(points.first().time, now.minus(Duration.ofHours(48)))
    val end = points.last().time
    val visible = points.filter { !it.time.isBefore(start) }
    if (visible.size < 2) {
        Text(stringResource(R.string.history_empty), style = MaterialTheme.typography.bodyMedium)
        return
    }
    val minV = visible.minOf { it.consumption }
    val maxV = visible.maxOf { it.consumption }
    val top = max(maxV, thresholds.redAbove) * 1.05
    val lineColor = MaterialTheme.colorScheme.primary
    val gridColor = MaterialTheme.colorScheme.outline
    val description = stringResource(R.string.chart_description, minV.roundToInt(), maxV.roundToInt())
    val span = max(1L, Duration.between(start, end).seconds).toFloat()
    val maxGap = Duration.ofMinutes(45)

    Column(Modifier.fillMaxWidth()) {
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(180.dp)
                .semantics { contentDescription = description },
        ) {
            fun x(t: Instant) = Duration.between(start, t).seconds / span * size.width
            fun y(v: Double) = (size.height * (1 - v / top)).toFloat()
            val dash = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))
            drawLine(levelColor(Level.GREEN), Offset(0f, y(thresholds.greenBelow)),
                Offset(size.width, y(thresholds.greenBelow)), strokeWidth = 2f, pathEffect = dash)
            drawLine(levelColor(Level.RED), Offset(0f, y(thresholds.redAbove)),
                Offset(size.width, y(thresholds.redAbove)), strokeWidth = 2f, pathEffect = dash)
            drawLine(gridColor, Offset(0f, size.height), Offset(size.width, size.height), strokeWidth = 1f)
            val path = Path()
            var prev: HistoryPoint? = null
            for (p in visible) {
                val gap = prev != null && Duration.between(prev.time, p.time) > maxGap
                if (prev == null || gap) path.moveTo(x(p.time), y(p.consumption)) else path.lineTo(x(p.time), y(p.consumption))
                prev = p
            }
            drawPath(path, lineColor, style = Stroke(width = 4f, cap = StrokeCap.Round))
        }
        Row(Modifier.fillMaxWidth()) {
            Text(
                stringResource(
                    R.string.history_axis,
                    formatDayClock(start, ZoneId.systemDefault()),
                    formatDayClock(end, ZoneId.systemDefault()),
                ),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
