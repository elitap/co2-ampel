package io.github.elitap.co2ampel.data

import io.github.elitap.co2ampel.domain.History
import io.github.elitap.co2ampel.domain.HistoryPoint
import io.github.elitap.co2ampel.domain.Quality
import io.github.elitap.co2ampel.domain.Snapshot
import io.github.elitap.co2ampel.domain.Thresholds
import io.github.elitap.co2ampel.domain.Zone
import io.github.elitap.co2ampel.domain.ZoneReading
import kotlinx.serialization.json.Json
import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * Robustes Parsen der veröffentlichten Dateien: unbekannte Felder werden ignoriert,
 * Werte außerhalb des plausiblen Bereichs verworfen, Fehler führen nie zu einem Absturz
 * (Ergebnis null bzw. leere Liste).
 */
object Co2Parser {
    const val MIN_VALUE = 0.0
    const val MAX_VALUE = 1500.0
    private val ZONE_CODE = Regex("^[A-Z]{2}(-[A-Z0-9]{1,4})?$")

    val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        explicitNulls = false
        isLenient = false
    }

    fun isValidZoneCode(code: String): Boolean = ZONE_CODE.matches(code)

    fun sanitizeValue(v: Double?): Double? =
        v?.takeIf { !it.isNaN() && !it.isInfinite() && it >= MIN_VALUE && it <= MAX_VALUE }

    fun parseInstant(s: String?): Instant? =
        if (s.isNullOrBlank()) null else try {
            Instant.parse(s)
        } catch (_: DateTimeParseException) {
            null
        }

    fun sanitizeThresholds(dto: ThresholdsDto?): Thresholds {
        val g = dto?.greenBelow
        val r = dto?.redAbove
        return if (g != null && r != null && g > 0 && g <= r && r <= MAX_VALUE) Thresholds(g, r) else Thresholds()
    }

    fun parseLatest(text: String): Snapshot? = runCatching {
        val dto = json.decodeFromString(LatestDto.serializer(), text)
        val readings = dto.zones
            .filter { isValidZoneCode(it.zone) }
            .associate { e ->
                e.zone to ZoneReading(
                    zone = Zone(e.zone, e.name, e.nameEn),
                    timestamp = parseInstant(e.timestamp),
                    consumption = sanitizeValue(e.consumption),
                    production = sanitizeValue(e.production),
                    quality = if (sanitizeValue(e.consumption) == null) Quality.UNKNOWN else Quality.parse(e.quality),
                )
            }
        Snapshot(
            generatedAt = parseInstant(dto.generatedAt),
            thresholds = sanitizeThresholds(dto.thresholds),
            readings = readings,
            usesEntsoe = dto.attribution.any { it.source.contains("ENTSO-E", ignoreCase = true) },
        )
    }.getOrNull()

    fun parseZones(text: String): List<Zone> = runCatching {
        json.decodeFromString(ZonesDto.serializer(), text).zones
            .filter { isValidZoneCode(it.zone) }
            .map { Zone(it.zone, it.name, it.nameEn) }
            .distinctBy { it.code }
    }.getOrDefault(emptyList())

    fun parseHistory(text: String): History? = runCatching {
        val dto = json.decodeFromString(HistoryDto.serializer(), text)
        val points = dto.points.mapNotNull { p ->
            val t = parseInstant(p.t) ?: return@mapNotNull null
            val c = sanitizeValue(p.consumption) ?: return@mapNotNull null
            HistoryPoint(t, c, Quality.parse(p.quality))
        }.sortedBy { it.time }
        History(dto.zone, points)
    }.getOrNull()
}
