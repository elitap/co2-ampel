package io.github.elitap.co2ampel.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.elitap.co2ampel.data.Co2Repository
import io.github.elitap.co2ampel.widget.updateAllWidgets
import java.util.concurrent.TimeUnit

/** Lädt latest.json und aktualisiert alle Widgets. Läuft nur mit Netz. */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val result = runCatching { Co2Repository(applicationContext).latest() }.getOrNull()
        runCatching { updateAllWidgets(applicationContext) }
        return if (result?.fromNetwork == true) Result.success() else Result.retry()
    }
}

object RefreshScheduler {
    private const val PERIODIC = "co2_refresh_periodic"
    private const val ONCE = "co2_refresh_once"

    private val networkConstraint = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build()

    /** Alle 15 Minuten (Minimum von WorkManager), nur mit Netz. */
    fun schedule(context: Context) {
        val request = PeriodicWorkRequestBuilder<RefreshWorker>(15, TimeUnit.MINUTES)
            .setConstraints(networkConstraint)
            .build()
        WorkManager.getInstance(context)
            .enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun refreshNow(context: Context) {
        val request = OneTimeWorkRequestBuilder<RefreshWorker>()
            .setConstraints(networkConstraint)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(ONCE, ExistingWorkPolicy.REPLACE, request)
    }
}
