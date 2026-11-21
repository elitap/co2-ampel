package io.github.elitap.co2ampel.widget

import io.github.elitap.co2ampel.domain.Level
import io.github.elitap.co2ampel.domain.Snapshot
import io.github.elitap.co2ampel.domain.formatValue
import io.github.elitap.co2ampel.domain.isOutdated
import io.github.elitap.co2ampel.domain.levelFor
import java.time.Duration
import java.time.Instant

/** Anzeigezustand eines Widgets (rein, testbar). */
data class WidgetModel(
    val zone: String,
    val level: Level,
    val value: String?,
    val dataTime: Instant?,
    val outdated: Boolean,
    val hasData: Boolean,
)

/** Ein Abruf, der länger als das zurückliegt, gilt als gescheitert (kein Netz) -> "veraltet". */
val MAX_FETCH_AGE: Duration = Duration.ofMinutes(45)

fun widgetModel(snapshot: Snapshot?, fetchedAt: Instant?, zone: String, now: Instant): WidgetModel {
    val reading = snapshot?.readings?.get(zone)
    val value = reading?.consumption
    val fetchTooOld = fetchedAt == null || Duration.between(fetchedAt, now) > MAX_FETCH_AGE
    return WidgetModel(
        zone = zone,
        level = if (snapshot == null) Level.UNKNOWN else levelFor(value, snapshot.thresholds),
        value = formatValue(value),
        dataTime = reading?.timestamp,
        outdated = snapshot != null && (isOutdated(reading, now) || fetchTooOld),
        hasData = value != null,
    )
}
