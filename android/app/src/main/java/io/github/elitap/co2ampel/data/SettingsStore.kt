package io.github.elitap.co2ampel.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

/** Einstellungen: gewählte Zone der App und Zone je Widget (Default AT). */
class SettingsStore(context: Context) {
    private val store = context.applicationContext.dataStore

    val selectedZone: Flow<String> = store.data.map { prefs ->
        prefs[APP_ZONE]?.takeIf(Co2Parser::isValidZoneCode) ?: DEFAULT_ZONE
    }

    suspend fun setSelectedZone(zone: String) {
        if (!Co2Parser.isValidZoneCode(zone)) return
        store.edit { it[APP_ZONE] = zone }
    }

    suspend fun widgetZone(appWidgetId: Int): String =
        store.data.first()[widgetKey(appWidgetId)]?.takeIf(Co2Parser::isValidZoneCode) ?: DEFAULT_ZONE

    suspend fun setWidgetZone(appWidgetId: Int, zone: String) {
        if (!Co2Parser.isValidZoneCode(zone)) return
        store.edit { it[widgetKey(appWidgetId)] = zone }
    }

    suspend fun removeWidget(appWidgetId: Int) {
        store.edit { it.remove(widgetKey(appWidgetId)) }
    }

    companion object {
        const val DEFAULT_ZONE = "AT"
        private val APP_ZONE = stringPreferencesKey("app_zone")
        private fun widgetKey(id: Int) = stringPreferencesKey("widget_zone_$id")
    }
}
