package io.github.elitap.co2ampel.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import io.github.elitap.co2ampel.R
import io.github.elitap.co2ampel.domain.Zone

/** Filtert Zonen nach Code oder Name (beide Sprachen), Groß-/Kleinschreibung egal. */
fun filterZones(zones: List<Zone>, query: String): List<Zone> {
    val q = query.trim()
    if (q.isEmpty()) return zones
    return zones.filter {
        it.code.contains(q, ignoreCase = true) || it.nameDe.contains(q, ignoreCase = true) ||
            it.nameEn.contains(q, ignoreCase = true)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ZonePickerScreen(
    title: String,
    zones: List<Zone>,
    selected: String,
    onSelect: (String) -> Unit,
    onBack: (() -> Unit)?,
) {
    var query by rememberSaveable { mutableStateOf("") }
    val language = LocalConfiguration.current.locales[0].language
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title) },
                navigationIcon = {
                    if (onBack != null) {
                        IconButton(onClick = onBack) {
                            Icon(painterResource(R.drawable.ic_back), contentDescription = stringResource(R.string.action_back))
                        }
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it.take(40) },
                label = { Text(stringResource(R.string.search_zone)) },
                leadingIcon = { Icon(painterResource(R.drawable.ic_search), contentDescription = null) },
                singleLine = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
            )
            if (zones.isEmpty()) {
                Text(
                    stringResource(R.string.zones_unavailable),
                    modifier = Modifier.padding(16.dp),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            val sorted = zones.sortedBy { it.displayName(language) }
            LazyColumn(Modifier.fillMaxSize()) {
                items(filterZones(sorted, query), key = { it.code }) { zone ->
                    ListItem(
                        headlineContent = { Text(zone.displayName(language)) },
                        supportingContent = { Text(zone.code) },
                        leadingContent = {
                            RadioButton(selected = zone.code == selected, onClick = null)
                        },
                        modifier = Modifier.clickable(role = Role.RadioButton) { onSelect(zone.code) },
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}
