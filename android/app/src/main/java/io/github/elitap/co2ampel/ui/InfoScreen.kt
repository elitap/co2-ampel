package io.github.elitap.co2ampel.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.github.elitap.co2ampel.R
import io.github.elitap.co2ampel.domain.Thresholds
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InfoScreen(thresholds: Thresholds, onBack: () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.info_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(painterResource(R.drawable.ic_back), contentDescription = stringResource(R.string.action_back))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Section(R.string.info_method_title, stringResource(R.string.info_method))
            Section(
                R.string.info_levels_title,
                stringResource(R.string.info_levels, thresholds.greenBelow.roundToInt(), thresholds.redAbove.roundToInt()),
            )
            Section(R.string.info_quality_title, stringResource(R.string.info_quality))
            Section(R.string.info_sources_title, stringResource(R.string.info_sources))
            Section(R.string.info_privacy_title, stringResource(R.string.info_privacy))
            Text(stringResource(R.string.info_source_code), style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
private fun Section(title: Int, body: String) {
    Text(
        stringResource(title),
        style = MaterialTheme.typography.titleMedium,
        modifier = Modifier
            .padding(top = 8.dp)
            .semantics { heading() },
    )
    Text(body, style = MaterialTheme.typography.bodyMedium)
}
