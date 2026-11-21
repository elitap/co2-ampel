package io.github.elitap.co2ampel

import io.github.elitap.co2ampel.domain.Age
import io.github.elitap.co2ampel.domain.ageOf
import io.github.elitap.co2ampel.domain.formatClock
import io.github.elitap.co2ampel.domain.formatDayClock
import io.github.elitap.co2ampel.domain.formatValue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.util.Locale

class TimeFormatTest {
    private val now = Instant.parse("2026-11-21T20:00:00Z")
    private fun ago(minutes: Long) = now.minus(Duration.ofMinutes(minutes))

    @Test
    fun relativeAge() {
        assertEquals(Age.JustNow, ageOf(now, now))
        assertEquals(Age.JustNow, ageOf(now.plusSeconds(120), now)) // Uhrzeit in der Zukunft
        assertEquals(Age.Minutes(1), ageOf(ago(1), now))
        assertEquals(Age.Minutes(59), ageOf(ago(59), now))
        assertEquals(Age.Hours(1), ageOf(ago(60), now))
        assertEquals(Age.Hours(2), ageOf(ago(179), now))
        assertEquals(Age.Hours(47), ageOf(ago(47 * 60 + 59), now))
        assertEquals(Age.Days(2), ageOf(ago(48 * 60), now))
    }

    @Test
    fun clockInLocalTimeZone() {
        val vienna = ZoneId.of("Europe/Vienna")
        assertEquals("19:00", formatClock(Instant.parse("2026-11-21T18:00:00Z"), vienna, Locale.GERMAN))
        // Sommerzeit: UTC+2
        assertEquals("14:15", formatClock(Instant.parse("2026-07-01T12:15:00Z"), vienna, Locale.GERMAN))
        assertEquals("21.11. 19:00", formatDayClock(Instant.parse("2026-11-21T18:00:00Z"), vienna, Locale.GERMAN))
        assertEquals("Nov 21, 19:00", formatDayClock(Instant.parse("2026-11-21T18:00:00Z"), vienna, Locale.ENGLISH))
    }

    @Test
    fun valueRounding() {
        assertEquals("290", formatValue(289.7))
        assertEquals("0", formatValue(0.2))
        assertNull(formatValue(null))
    }
}
