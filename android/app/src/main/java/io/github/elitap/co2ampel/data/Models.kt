package io.github.elitap.co2ampel.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Transportmodelle für die veröffentlichten JSON-Dateien (siehe docs/schema.json).
 * Alle Felder haben Standardwerte; unbekannte Felder werden ignoriert.
 */

@Serializable
data class ThresholdsDto(
    @SerialName("green_below") val greenBelow: Double? = null,
    @SerialName("red_above") val redAbove: Double? = null,
)

@Serializable
data class AttributionDto(
    val source: String = "",
    val license: String = "",
    val url: String = "",
)

@Serializable
data class ZoneEntryDto(
    val zone: String = "",
    val name: String = "",
    @SerialName("name_en") val nameEn: String = "",
    val timestamp: String? = null,
    val consumption: Double? = null,
    val production: Double? = null,
    val quality: String? = null,
)

@Serializable
data class LatestDto(
    @SerialName("generated_at") val generatedAt: String? = null,
    val thresholds: ThresholdsDto? = null,
    val attribution: List<AttributionDto> = emptyList(),
    val zones: List<ZoneEntryDto> = emptyList(),
)

@Serializable
data class ZoneInfoDto(
    val zone: String = "",
    val name: String = "",
    @SerialName("name_en") val nameEn: String = "",
)

@Serializable
data class ZonesDto(val zones: List<ZoneInfoDto> = emptyList())

@Serializable
data class HistoryPointDto(
    val t: String = "",
    val consumption: Double? = null,
    val production: Double? = null,
    val quality: String? = null,
)

@Serializable
data class HistoryDto(
    val zone: String = "",
    val points: List<HistoryPointDto> = emptyList(),
)
