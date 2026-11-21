package io.github.elitap.co2ampel.widget

import android.appwidget.AppWidgetManager
import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.LocalContext
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.color.ColorProvider
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.layout.width
import androidx.glance.semantics.contentDescription
import androidx.glance.semantics.semantics
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import io.github.elitap.co2ampel.R
import io.github.elitap.co2ampel.data.Co2Repository
import io.github.elitap.co2ampel.data.SettingsStore
import io.github.elitap.co2ampel.domain.Level
import io.github.elitap.co2ampel.domain.formatClock
import io.github.elitap.co2ampel.ui.MainActivity
import io.github.elitap.co2ampel.work.RefreshScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId

private val textPrimary = ColorProvider(day = Color(0xFF191C1A), night = Color(0xFFE1E3DF))
private val textSecondary = ColorProvider(day = Color(0xFF404943), night = Color(0xFFC0C9C1))

fun dotDrawable(level: Level): Int = when (level) {
    Level.GREEN -> R.drawable.dot_green
    Level.YELLOW -> R.drawable.dot_yellow
    Level.RED -> R.drawable.dot_red
    Level.UNKNOWN -> R.drawable.dot_unknown
}

fun levelShortText(level: Level): Int = when (level) {
    Level.GREEN -> R.string.level_green_short
    Level.YELLOW -> R.string.level_yellow_short
    Level.RED -> R.string.level_red_short
    Level.UNKNOWN -> R.string.level_unknown_short
}

/** Gemeinsame Basis: klein = Ampelpunkt + Wert; mittel = zusätzlich Zone und Uhrzeit. */
abstract class Co2WidgetBase(private val medium: Boolean) : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val appWidgetId = GlanceAppWidgetManager(context).getAppWidgetId(id)
        val zone = SettingsStore(context).widgetZone(appWidgetId)
        val cached = runCatching { Co2Repository(context).cachedLatest() }.getOrNull()
        val model = widgetModel(cached?.snapshot, cached?.fetchedAt, zone, Instant.now())
        provideContent { WidgetContent(model, medium) }
    }
}

class SmallWidget : Co2WidgetBase(medium = false)
class MediumWidget : Co2WidgetBase(medium = true)

@Composable
private fun WidgetContent(model: WidgetModel, medium: Boolean) {
    val context = LocalContext.current
    val unit = context.getString(R.string.unit)
    val levelText = context.getString(levelShortText(model.level))
    val valueText = model.value ?: context.getString(R.string.value_missing)
    val description = buildString {
        append(model.zone).append(": ").append(valueText).append(' ').append(unit).append(", ").append(levelText)
        if (model.outdated) append(", ").append(context.getString(R.string.stale_short))
    }
    val root = GlanceModifier
        .fillMaxSize()
        .background(ImageProvider(R.drawable.widget_background))
        .padding(8.dp)
        .clickable(actionStartActivity<MainActivity>())
        .semantics { contentDescription = description }

    if (!medium) {
        Column(modifier = root, horizontalAlignment = Alignment.CenterHorizontally,
            verticalAlignment = Alignment.CenterVertically) {
            Image(ImageProvider(dotDrawable(model.level)), contentDescription = null, modifier = GlanceModifier.size(22.dp))
            Text(valueText, style = TextStyle(color = textPrimary, fontSize = 18.sp, fontWeight = FontWeight.Bold))
            Text(
                if (model.outdated) context.getString(R.string.stale_short) else levelText,
                style = TextStyle(color = textSecondary, fontSize = 11.sp),
            )
        }
    } else {
        Row(modifier = root, verticalAlignment = Alignment.CenterVertically) {
            Image(ImageProvider(dotDrawable(model.level)), contentDescription = null, modifier = GlanceModifier.size(40.dp))
            Spacer(GlanceModifier.width(12.dp))
            Column {
                Text("$valueText g", style = TextStyle(color = textPrimary, fontSize = 22.sp, fontWeight = FontWeight.Bold))
                Text(levelText, style = TextStyle(color = textSecondary, fontSize = 13.sp))
                val time = model.dataTime?.let { formatClock(it, ZoneId.systemDefault()) } ?: "–"
                Text("${model.zone} · $time", style = TextStyle(color = textSecondary, fontSize = 13.sp))
                if (model.outdated) {
                    Text(context.getString(R.string.stale_short),
                        style = TextStyle(color = textSecondary, fontSize = 12.sp, fontWeight = FontWeight.Bold))
                }
            }
        }
    }
}

suspend fun updateAllWidgets(context: Context) {
    SmallWidget().updateAll(context)
    MediumWidget().updateAll(context)
}

abstract class Co2WidgetReceiverBase : GlanceAppWidgetReceiver() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        super.onUpdate(context, appWidgetManager, appWidgetIds)
        // stellt die periodische Aktualisierung sicher (z. B. nach einem Neustart)
        RefreshScheduler.schedule(context)
    }

    override fun onDeleted(context: Context, appWidgetIds: IntArray) {
        super.onDeleted(context, appWidgetIds)
        val appContext = context.applicationContext
        scope.launch {
            val settings = SettingsStore(appContext)
            appWidgetIds.forEach { runCatching { settings.removeWidget(it) } }
        }
    }
}

class SmallWidgetReceiver : Co2WidgetReceiverBase() {
    override val glanceAppWidget: GlanceAppWidget = SmallWidget()
}

class MediumWidgetReceiver : Co2WidgetReceiverBase() {
    override val glanceAppWidget: GlanceAppWidget = MediumWidget()
}
