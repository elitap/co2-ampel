package io.github.elitap.co2ampel

import io.github.elitap.co2ampel.domain.Level
import io.github.elitap.co2ampel.domain.Quality
import io.github.elitap.co2ampel.domain.Snapshot
import io.github.elitap.co2ampel.domain.Thresholds
import io.github.elitap.co2ampel.domain.Zone
import io.github.elitap.co2ampel.domain.ZoneReading
import io.github.elitap.co2ampel.ui.filterZones
import io.github.elitap.co2ampel.widget.widgetModel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Duration
import java.time.Instant

class WidgetModelTest {
    private val now = Instant.parse("2026-11-21T20:00:00Z")
    private val at = Zone("AT", "Österreich", "Austria")
    private val snapshot = Snapshot(
        generatedAt = now,
        thresholds = Thresholds(),
        readings = mapOf("AT" to ZoneReading(at, now.minus(Duration.ofHours(2)), 120.4, 80.0, Quality.MEASURED)),
        usesEntsoe = false,
    )

    @Test
    fun freshData() {
        val m = widgetModel(snapshot, now.minus(Duration.ofMinutes(10)), "AT", now)
        assertEquals(Level.GREEN, m.level)
        assertEquals("120", m.value)
        assertFalse(m.outdated)
        assertTrue(m.hasData)
    }

    @Test
    fun offlineShowsLastValueAsOutdated() {
        val m = widgetModel(snapshot, now.minus(Duration.ofHours(2)), "AT", now)
        assertEquals("120", m.value)
        assertTrue(m.outdated)
    }

    @Test
    fun unknownZoneAndNoCache() {
        val m = widgetModel(snapshot, now, "DK", now)
        assertEquals(Level.UNKNOWN, m.level)
        assertNull(m.value)
        assertFalse(m.hasData)
        val empty = widgetModel(null, null, "AT", now)
        assertEquals(Level.UNKNOWN, empty.level)
        assertFalse(empty.outdated)
    }

    @Test
    fun zoneSearch() {
        val zones = listOf(at, Zone("DE", "Deutschland", "Germany"), Zone("CH", "Schweiz", "Switzerland"))
        assertEquals(listOf("DE"), filterZones(zones, "germ").map { it.code })
        assertEquals(listOf("CH"), filterZones(zones, "schw").map { it.code })
        assertEquals(listOf("AT"), filterZones(zones, " at ").map { it.code })
        assertEquals(3, filterZones(zones, "").size)
    }
}
