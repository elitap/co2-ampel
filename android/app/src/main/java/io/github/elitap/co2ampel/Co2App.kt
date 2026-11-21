package io.github.elitap.co2ampel

import android.app.Application
import io.github.elitap.co2ampel.work.RefreshScheduler

class Co2App : Application() {
    override fun onCreate() {
        super.onCreate()
        RefreshScheduler.schedule(this)
    }
}
