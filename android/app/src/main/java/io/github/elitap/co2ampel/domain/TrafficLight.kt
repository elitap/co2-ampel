package io.github.elitap.co2ampel.domain

import java.time.Duration
import java.time.Instant

enum class Level { GREEN, YELLOW, RED, UNKNOWN }

/** Ampelstufe: grün < greenBelow, gelb greenBelow..redAbove, rot > redAbove. */
fun levelFor(value: Double?, thresholds: Thresholds): Level = when {
    value == null || value.isNaN() || value < 0 -> Level.UNKNOWN
    value < thresholds.greenBelow -> Level.GREEN
    value > thresholds.redAbove -> Level.RED
    else -> Level.YELLOW
}

/** Hinweis, der zu einem Wert angezeigt wird (höchste Priorität zuerst). */
enum class Hint { NONE, FORECAST, ESTIMATED, STALE, UNKNOWN }

/** Wie stale_after_hours im Backend: Energy-Charts veröffentlicht mit 1–4 h Verzug. */
val MAX_DATA_AGE: Duration = Duration.ofHours(4)

/** Daten älter als 4 h oder als veraltet markiert. */
fun isOutdated(reading: ZoneReading?, now: Instant): Boolean {
    if (reading?.timestamp == null || reading.consumption == null) return true
    if (reading.quality == Quality.STALE || reading.quality == Quality.UNKNOWN) return true
    return Duration.between(reading.timestamp, now) > MAX_DATA_AGE
}

fun hintFor(reading: ZoneReading?, now: Instant): Hint = when {
    reading?.consumption == null -> Hint.UNKNOWN
    isOutdated(reading, now) -> Hint.STALE
    reading.quality == Quality.ESTIMATED -> Hint.ESTIMATED
    reading.quality == Quality.FORECAST -> Hint.FORECAST
    else -> Hint.NONE
}
