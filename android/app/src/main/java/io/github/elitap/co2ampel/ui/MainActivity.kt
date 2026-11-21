package io.github.elitap.co2ampel.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.elitap.co2ampel.R
import io.github.elitap.co2ampel.domain.Thresholds
import io.github.elitap.co2ampel.ui.theme.Co2Theme
import kotlinx.coroutines.delay
import java.time.Instant

private enum class Screen { HOME, ZONES, INFO }

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent { Co2Theme { AppRoot(viewModel) } }
    }
}

@Composable
private fun AppRoot(viewModel: MainViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var screen by rememberSaveable { mutableStateOf(Screen.HOME) }
    var now by remember { mutableStateOf(Instant.now()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(30_000)
            now = Instant.now()
        }
    }
    BackHandler(enabled = screen != Screen.HOME) { screen = Screen.HOME }
    when (screen) {
        Screen.HOME -> HomeScreen(
            state = state,
            now = now,
            onZones = {
                viewModel.loadZones()
                screen = Screen.ZONES
            },
            onInfo = { screen = Screen.INFO },
            onRefresh = {
                now = Instant.now()
                viewModel.refresh()
            },
        )
        Screen.ZONES -> ZonePickerScreen(
            title = stringResource(R.string.select_zone),
            zones = state.zones.ifEmpty { state.latest?.snapshot?.zones.orEmpty() },
            selected = state.zone,
            onSelect = {
                viewModel.selectZone(it)
                screen = Screen.HOME
            },
            onBack = { screen = Screen.HOME },
        )
        Screen.INFO -> InfoScreen(
            thresholds = state.latest?.snapshot?.thresholds ?: Thresholds(),
            onBack = { screen = Screen.HOME },
        )
    }
}
