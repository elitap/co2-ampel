package io.github.elitap.co2ampel.data

import android.content.Context
import io.github.elitap.co2ampel.BuildConfig
import io.github.elitap.co2ampel.domain.History
import io.github.elitap.co2ampel.domain.Snapshot
import io.github.elitap.co2ampel.domain.Zone
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.time.Instant
import java.util.concurrent.TimeUnit

data class LatestResult(val snapshot: Snapshot, val fetchedAt: Instant, val fromNetwork: Boolean)

/**
 * Lädt die Dateien ausschließlich von der GitHub-Pages-URL (BuildConfig.DATA_BASE_URL, nur HTTPS)
 * und hält die letzte gültige Antwort als Datei vor (für Offline-Betrieb und das Widget).
 */
class Co2Repository(
    context: Context,
    private val baseUrl: String = BuildConfig.DATA_BASE_URL,
    private val client: OkHttpClient = sharedClient,
) {
    private val cacheDir = File(context.applicationContext.filesDir, "data").apply { mkdirs() }

    init {
        require(baseUrl.startsWith("https://")) { "Nur HTTPS erlaubt" }
    }

    private suspend fun download(path: String): String? = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder().url(baseUrl + path).header("Accept", "application/json").build()
            client.newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) return@use null
                val body = resp.body
                if (body.contentLength() > MAX_BYTES) return@use null
                body.string().takeIf { it.length <= MAX_BYTES }
            }
        } catch (_: IOException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    private fun cacheFile(name: String) = File(cacheDir, name)

    private suspend fun store(name: String, text: String) = withContext(Dispatchers.IO) {
        runCatching {
            val tmp = cacheFile("$name.tmp")
            tmp.writeText(text)
            tmp.renameTo(cacheFile(name))
        }
    }

    private suspend fun readCache(name: String): Pair<String, Instant>? = withContext(Dispatchers.IO) {
        runCatching {
            val f = cacheFile(name)
            if (f.isFile) f.readText() to Instant.ofEpochMilli(f.lastModified()) else null
        }.getOrNull()
    }

    suspend fun cachedLatest(): LatestResult? {
        val (text, at) = readCache(LATEST) ?: return null
        val snap = Co2Parser.parseLatest(text) ?: return null
        return LatestResult(snap, at, fromNetwork = false)
    }

    /** Netz zuerst; bei Fehler der zuletzt gespeicherte Stand (fromNetwork = false). */
    suspend fun latest(): LatestResult? {
        val text = download(LATEST)
        val snap = text?.let { Co2Parser.parseLatest(it) }
        if (text != null && snap != null && snap.readings.isNotEmpty()) {
            store(LATEST, text)
            return LatestResult(snap, Instant.now(), fromNetwork = true)
        }
        return cachedLatest()
    }

    suspend fun zones(): List<Zone> {
        download(ZONES)?.let { text ->
            val zones = Co2Parser.parseZones(text)
            if (zones.isNotEmpty()) {
                store(ZONES, text)
                return zones
            }
        }
        readCache(ZONES)?.let { (text, _) -> Co2Parser.parseZones(text).takeIf { it.isNotEmpty() }?.let { return it } }
        return cachedLatest()?.snapshot?.zones.orEmpty()
    }

    suspend fun history(zone: String): History? {
        if (!Co2Parser.isValidZoneCode(zone)) return null
        val name = "history_$zone.json"
        download("history/$zone.json")?.let { text ->
            Co2Parser.parseHistory(text)?.let {
                store(name, text)
                return it
            }
        }
        return readCache(name)?.let { (text, _) -> Co2Parser.parseHistory(text) }
    }

    companion object {
        private const val LATEST = "latest.json"
        private const val ZONES = "zones.json"
        private const val MAX_BYTES = 2_000_000L

        val sharedClient: OkHttpClient by lazy {
            OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .callTimeout(30, TimeUnit.SECONDS)
                .followSslRedirects(true)
                .followRedirects(true)
                .retryOnConnectionFailure(true)
                .build()
        }
    }
}
