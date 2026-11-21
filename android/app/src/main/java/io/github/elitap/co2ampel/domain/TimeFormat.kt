package io.github.elitap.co2ampel.domain

import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Alter eines Werts, für "vor x Minuten" (Formatierung über Plural-Ressourcen). */
sealed interface Age {
    data object JustNow : Age
    data class Minutes(val n: Long) : Age
    data class Hours(val n: Long) : Age
    data class Days(val n: Long) : Age
}

fun ageOf(then: Instant, now: Instant): Age {
    val minutes = Duration.between(then, now).toMinutes().coerceAtLeast(0)
    return when {
        minutes < 1 -> Age.JustNow
        minutes < 60 -> Age.Minutes(minutes)
        minutes < 48 * 60 -> Age.Hours(minutes / 60)
        else -> Age.Days(minutes / (24 * 60))
    }
}

/** Uhrzeit "HH:mm" in der lokalen Zeitzone. */
fun formatClock(instant: Instant, zone: ZoneId, locale: Locale = Locale.getDefault()): String =
    DateTimeFormatter.ofPattern("HH:mm", locale).withZone(zone).format(instant)

/** Datum und Uhrzeit, z. B. "21.11. 14:15". */
fun formatDayClock(instant: Instant, zone: ZoneId, locale: Locale = Locale.getDefault()): String {
    val pattern = if (locale.language == "de") "dd.MM. HH:mm" else "MMM d, HH:mm"
    return DateTimeFormatter.ofPattern(pattern, locale).withZone(zone).format(instant)
}

/** Gerundeter Anzeigewert ohne Nachkommastellen. */
fun formatValue(value: Double?): String? = value?.let { Math.round(it).toString() }
