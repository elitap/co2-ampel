package io.github.elitap.co2ampel.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.elitap.co2ampel.data.Co2Repository
import io.github.elitap.co2ampel.data.LatestResult
import io.github.elitap.co2ampel.data.SettingsStore
import io.github.elitap.co2ampel.domain.History
import io.github.elitap.co2ampel.domain.Zone
import io.github.elitap.co2ampel.widget.updateAllWidgets
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class UiState(
    val zone: String = SettingsStore.DEFAULT_ZONE,
    val latest: LatestResult? = null,
    val history: History? = null,
    val zones: List<Zone> = emptyList(),
    val loading: Boolean = false,
    val error: Boolean = false,
)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val repo = Co2Repository(app)
    private val settings = SettingsStore(app)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            settings.selectedZone.distinctUntilChanged().collect { zone ->
                _state.update { it.copy(zone = zone, history = null) }
                loadHistory(zone)
            }
        }
        viewModelScope.launch {
            val cached = runCatching { repo.cachedLatest() }.getOrNull()
            _state.update { it.copy(latest = it.latest ?: cached) }
            refresh()
        }
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(loading = true) }
            val result = runCatching { repo.latest() }.getOrNull()
            _state.update {
                it.copy(latest = result ?: it.latest, loading = false, error = result?.fromNetwork != true)
            }
            loadHistory(_state.value.zone)
            runCatching { updateAllWidgets(getApplication()) }
        }
    }

    fun loadZones() {
        viewModelScope.launch {
            val zones = runCatching { repo.zones() }.getOrDefault(emptyList())
            _state.update { it.copy(zones = zones) }
        }
    }

    fun selectZone(zone: String) {
        viewModelScope.launch { settings.setSelectedZone(zone) }
    }

    private suspend fun loadHistory(zone: String) {
        val history = runCatching { repo.history(zone) }.getOrNull()
        _state.update { if (it.zone == zone) it.copy(history = history) else it }
    }
}
