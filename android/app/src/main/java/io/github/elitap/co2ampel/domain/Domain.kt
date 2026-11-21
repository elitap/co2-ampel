package io.github.elitap.co2ampel.domain

import java.time.Instant

/** Qualitätsflag eines Werts (wie im Backend). */
enum class Quality {
    MEASURED, FORECAST, STALE, ESTIMATED, UNKNOWN;

    companion object {
        fun parse(value: String?): Quality = when (value?.lowercase()) {
            "measured" -> MEASURED
            "forecast" -> FORECAST
            "stale" -> STALE
            "estimated" -> ESTIMATED
            else -> UNKNOWN
        }
    }
}

/** Ampelgrenzen in gCO2eq/kWh. */
data class Thresholds(val greenBelow: Double = DEFAULT_GREEN, val redAbove: Double = DEFAULT_RED) {
    companion object {
        const val DEFAULT_GREEN = 150.0
        const val DEFAULT_RED = 300.0
    }
}

data class Zone(val code: String, val nameDe: String, val nameEn: String) {
    fun displayName(language: String): String {
        val preferred = if (language == "de") nameDe else nameEn
        return preferred.ifBlank { nameDe.ifBlank { nameEn.ifBlank { code } } }
    }
}

data class ZoneReading(
    val zone: Zone,
    val timestamp: Instant?,
    val consumption: Double?,
    val production: Double?,
    val quality: Quality,
)

data class Snapshot(
    val generatedAt: Instant?,
    val thresholds: Thresholds,
    val readings: Map<String, ZoneReading>,
    val usesEntsoe: Boolean,
) {
    val zones: List<Zone> get() = readings.values.map { it.zone }.sortedBy { it.code }
}

data class HistoryPoint(val time: Instant, val consumption: Double, val quality: Quality)

data class History(val zone: String, val points: List<HistoryPoint>)
