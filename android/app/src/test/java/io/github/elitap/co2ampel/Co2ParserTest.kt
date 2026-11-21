package io.github.elitap.co2ampel

import io.github.elitap.co2ampel.data.Co2Parser
import io.github.elitap.co2ampel.domain.Quality
import io.github.elitap.co2ampel.domain.Thresholds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class Co2ParserTest {
    private val valid = """
        {
          "schema_version": 1, "kind": "latest", "generated_at": "2026-11-21T19:00:00Z",
          "attribution": [{"source": "Energy-Charts (Fraunhofer ISE), energy-charts.info, CC BY 4.0",
                           "license": "CC BY 4.0", "url": "https://energy-charts.info"}],
          "unit": "gCO2eq/kWh",
          "thresholds": {"green_below": 150, "red_above": 300, "unit": "gCO2eq/kWh"},
          "zones": [
            {"zone": "AT", "name": "Österreich", "name_en": "Austria", "timestamp": "2026-11-21T18:00:00Z",
             "consumption": 289.7, "production": 195.9, "quality": "measured", "level": "yellow"},
            {"zone": "DK", "name": "Dänemark", "name_en": "Denmark", "timestamp": null,
             "consumption": null, "production": null, "quality": "unknown", "level": "unknown"}
          ]
        }
    """.trimIndent()

    @Test
    fun parsesValidLatest() {
        val s = Co2Parser.parseLatest(valid)
        assertNotNull(s)
        s!!
        assertEquals(Instant.parse("2026-11-21T19:00:00Z"), s.generatedAt)
        assertEquals(Thresholds(150.0, 300.0), s.thresholds)
        val at = s.readings.getValue("AT")
        assertEquals(289.7, at.consumption!!, 1e-9)
        assertEquals(195.9, at.production!!, 1e-9)
        assertEquals(Quality.MEASURED, at.quality)
        assertEquals("Österreich", at.zone.displayName("de"))
        assertEquals("Austria", at.zone.displayName("en"))
        assertEquals(Quality.UNKNOWN, s.readings.getValue("DK").quality)
        assertFalse(s.usesEntsoe)
    }

    @Test
    fun ignoresUnknownFieldsAndQualities() {
        val text = valid
            .replace("\"unit\": \"gCO2eq/kWh\",", "\"unit\": \"gCO2eq/kWh\", \"new_field\": {\"x\": [1, 2]},")
            .replace("\"quality\": \"measured\"", "\"quality\": \"something-new\", \"extra\": true")
        val s = Co2Parser.parseLatest(text)
        assertNotNull(s)
        assertEquals(Quality.UNKNOWN, s!!.readings.getValue("AT").quality)
    }

    @Test
    fun rejectsOutOfRangeValues() {
        val s = Co2Parser.parseLatest(valid.replace("289.7", "1600").replace("195.9", "-3"))!!
        val at = s.readings.getValue("AT")
        assertNull(at.consumption)
        assertNull(at.production)
        assertEquals(Quality.UNKNOWN, at.quality)
    }

    @Test
    fun invalidThresholdsFallBackToDefaults() {
        val s = Co2Parser.parseLatest(valid.replace("\"green_below\": 150", "\"green_below\": 400"))!!
        assertEquals(Thresholds(), s.thresholds)
    }

    @Test
    fun garbageNeverThrows() {
        listOf("", "null", "[]", "{", "<html>", "{\"zones\": 5}", "{\"zones\": [{\"zone\": 7}]}").forEach {
            Co2Parser.parseLatest(it) // darf nicht werfen
        }
        assertNull(Co2Parser.parseLatest("<html>"))
        assertTrue(Co2Parser.parseZones("{").isEmpty())
        assertNull(Co2Parser.parseHistory("nope"))
    }

    @Test
    fun invalidZoneCodesAreDropped() {
        val s = Co2Parser.parseLatest(valid.replace("\"zone\": \"AT\"", "\"zone\": \"../../x\""))!!
        assertFalse(s.readings.containsKey("../../x"))
        assertTrue(Co2Parser.isValidZoneCode("DE-LU"))
        assertFalse(Co2Parser.isValidZoneCode("at"))
    }

    @Test
    fun parsesZonesAndHistory() {
        val zones = Co2Parser.parseZones(
            """{"kind":"zones","zones":[{"zone":"AT","name":"Österreich","name_en":"Austria"},{"zone":"bad"}]}""",
        )
        assertEquals(listOf("AT"), zones.map { it.code })
        val h = Co2Parser.parseHistory(
            """{"zone":"AT","points":[
                {"t":"2026-11-21T18:15:00Z","consumption":200,"production":100,"quality":"measured"},
                {"t":"2026-11-21T18:00:00Z","consumption":210,"production":null,"quality":"stale"},
                {"t":"broken","consumption":1},
                {"t":"2026-11-21T18:30:00Z","consumption":null}
            ]}""",
        )!!
        assertEquals(2, h.points.size)
        assertEquals(Instant.parse("2026-11-21T18:00:00Z"), h.points.first().time)
        assertEquals(Quality.STALE, h.points.first().quality)
    }
}
