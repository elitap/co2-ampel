package io.github.elitap.co2ampel.widget

import android.appwidget.AppWidgetManager
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.lifecycleScope
import io.github.elitap.co2ampel.R
import io.github.elitap.co2ampel.data.Co2Repository
import io.github.elitap.co2ampel.data.SettingsStore
import io.github.elitap.co2ampel.domain.Zone
import io.github.elitap.co2ampel.ui.ZonePickerScreen
import io.github.elitap.co2ampel.ui.theme.Co2Theme
import io.github.elitap.co2ampel.work.RefreshScheduler
import kotlinx.coroutines.launch

/** Zonenwahl pro Widget (Default AT). */
class WidgetConfigActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val appWidgetId = intent?.extras?.getInt(
            AppWidgetManager.EXTRA_APPWIDGET_ID,
            AppWidgetManager.INVALID_APPWIDGET_ID,
        ) ?: AppWidgetManager.INVALID_APPWIDGET_ID
        // Abbruch = Widget mit Default-Zone behalten (configuration_optional)
        setResult(RESULT_CANCELED, resultIntent(appWidgetId))
        if (appWidgetId == AppWidgetManager.INVALID_APPWIDGET_ID) {
            finish()
            return
        }
        val settings = SettingsStore(this)
        val repo = Co2Repository(this)
        setContent {
            Co2Theme {
                var zones by remember { mutableStateOf(emptyList<Zone>()) }
                var selected by remember { mutableStateOf(SettingsStore.DEFAULT_ZONE) }
                LaunchedEffect(appWidgetId) {
                    selected = settings.widgetZone(appWidgetId)
                    zones = runCatching { repo.zones() }.getOrDefault(emptyList())
                }
                ZonePickerScreen(
                    title = stringResource(R.string.widget_config_title),
                    zones = zones,
                    selected = selected,
                    onSelect = { zone -> save(appWidgetId, zone, settings) },
                    onBack = null,
                )
            }
        }
    }

    private fun save(appWidgetId: Int, zone: String, settings: SettingsStore) {
        lifecycleScope.launch {
            settings.setWidgetZone(appWidgetId, zone)
            runCatching { updateAllWidgets(applicationContext) }
            RefreshScheduler.schedule(applicationContext)
            RefreshScheduler.refreshNow(applicationContext)
            setResult(RESULT_OK, resultIntent(appWidgetId))
            finish()
        }
    }

    private fun resultIntent(appWidgetId: Int) =
        Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, appWidgetId)
}
