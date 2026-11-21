package io.github.elitap.co2ampel

import io.github.elitap.co2ampel.domain.Hint
import io.github.elitap.co2ampel.domain.Level
import io.github.elitap.co2ampel.domain.Quality
import io.github.elitap.co2ampel.domain.Thresholds
import io.github.elitap.co2ampel.domain.Zone
import io.github.elitap.co2ampel.domain.ZoneReading
import io.github.elitap.co2ampel.domain.hintFor
import io.github.elitap.co2ampel.domain.isOutdated
import io.github.elitap.co2ampel.domain.levelFor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Duration
import java.time.Instant

class TrafficLightTest {
    private val t = Thresholds(150.0, 300.0)

    @Test
    fun levelsAtBoundaries() {
        assertEquals(Level.GREEN, levelFor(0.0, t))
        assertEquals(Level.GREEN, levelFor(149.9, t))
        assertEquals(Level.YELLOW, levelFor(150.0, t))
        assertEquals(Level.YELLOW, levelFor(300.0, t))
        assertEquals(Level.RED, levelFor(300.1, t))
        assertEquals(Level.UNKNOWN, levelFor(null, t))
        assertEquals(Level.UNKNOWN, levelFor(Double.NaN, t))
        assertEquals(Level.UNKNOWN, levelFor(-1.0, t))
    }

    @Test
    fun customThresholdsFromJson() {
        val custom = Thresholds(100.0, 200.0)
        assertEquals(Level.YELLOW, levelFor(120.0, custom))
        assertEquals(Level.RED, levelFor(250.0, custom))
    }

    private val now = Instant.parse("2026-11-21T20:00:00Z")
    private fun reading(ageMinutes: Long, q: Quality, v: Double? = 100.0) =
        ZoneReading(Zone("AT", "Österreich", "Austria"), now.minus(Duration.ofMinutes(ageMinutes)), v, v, q)

    @Test
    fun outdatedAndHints() {
        assertFalse(isOutdated(reading(60, Quality.MEASURED), now))
        assertTrue(isOutdated(reading(241, Quality.MEASURED), now))
        assertTrue(isOutdated(reading(10, Quality.STALE), now))
        assertTrue(isOutdated(null, now))
        assertEquals(Hint.NONE, hintFor(reading(60, Quality.MEASURED), now))
        assertEquals(Hint.FORECAST, hintFor(reading(60, Quality.FORECAST), now))
        assertEquals(Hint.ESTIMATED, hintFor(reading(60, Quality.ESTIMATED), now))
        assertEquals(Hint.STALE, hintFor(reading(300, Quality.FORECAST), now))
        assertEquals(Hint.UNKNOWN, hintFor(reading(60, Quality.UNKNOWN, v = null), now))
    }
}
