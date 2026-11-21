package io.github.elitap.co2ampel.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.elitap.co2ampel.R
import io.github.elitap.co2ampel.domain.Age
import io.github.elitap.co2ampel.domain.Hint
import io.github.elitap.co2ampel.domain.Level
import io.github.elitap.co2ampel.domain.ZoneReading
import io.github.elitap.co2ampel.domain.ageOf
import io.github.elitap.co2ampel.domain.formatDayClock
import io.github.elitap.co2ampel.domain.formatValue
import io.github.elitap.co2ampel.domain.hintFor
import io.github.elitap.co2ampel.domain.levelFor
import io.github.elitap.co2ampel.ui.theme.levelColor
import io.github.elitap.co2ampel.ui.theme.onLevelColor
import java.time.Instant
import java.time.ZoneId

@Composable
fun levelText(level: Level): String = stringResource(
    when (level) {
        Level.GREEN -> R.string.level_green
        Level.YELLOW -> R.string.level_yellow
        Level.RED -> R.string.level_red
        Level.UNKNOWN -> R.string.level_unknown
    },
)

@Composable
fun ageText(age: Age): String = when (age) {
    Age.JustNow -> stringResource(R.string.age_just_now)
    is Age.Minutes -> pluralStringResource(R.plurals.age_minutes, age.n.toInt(), age.n.toInt())
    is Age.Hours -> pluralStringResource(R.plurals.age_hours, age.n.toInt(), age.n.toInt())
    is Age.Days -> pluralStringResource(R.plurals.age_days, age.n.toInt(), age.n.toInt())
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    state: UiState,
    now: Instant,
    onZones: () -> Unit,
    onInfo: () -> Unit,
    onRefresh: () -> Unit,
) {
    val language = LocalConfiguration.current.locales[0].language
    val snapshot = state.latest?.snapshot
    val reading: ZoneReading? = snapshot?.readings?.get(state.zone)
    val title = reading?.zone?.displayName(language) ?: state.zone
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title) },
                actions = {
                    IconButton(onClick = onZones) {
                        Icon(painterResource(R.drawable.ic_place), contentDescription = stringResource(R.string.action_zone))
                    }
                    IconButton(onClick = onRefresh) {
                        Icon(painterResource(R.drawable.ic_refresh), contentDescription = stringResource(R.string.action_refresh))
                    }
                    IconButton(onClick = onInfo) {
                        Icon(painterResource(R.drawable.ic_info), contentDescription = stringResource(R.string.action_info))
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
                .padding(horizontal = 20.dp, vertical = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            if (state.loading) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            val thresholds = snapshot?.thresholds ?: io.github.elitap.co2ampel.domain.Thresholds()
            val level = levelFor(reading?.consumption, thresholds)
            TrafficCircle(level = level, value = formatValue(reading?.consumption))
            Text(
                levelText(level),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                textAlign = TextAlign.Center,
            )

            IntensityRow(reading)

            reading?.timestamp?.let { ts ->
                Text(
                    stringResource(R.string.data_time, ageText(ageOf(ts, now)), formatDayClock(ts, ZoneId.systemDefault())),
                    style = MaterialTheme.typography.bodyMedium,
                    textAlign = TextAlign.Center,
                )
            }

            val hints = buildList {
                when (hintFor(reading, now)) {
                    Hint.UNKNOWN -> add(R.string.hint_unknown)
                    Hint.STALE -> add(R.string.hint_stale)
                    Hint.ESTIMATED -> add(R.string.hint_estimated)
                    Hint.FORECAST -> add(R.string.hint_forecast)
                    Hint.NONE -> Unit
                }
                if (state.latest != null && !state.latest.fromNetwork) add(R.string.hint_offline)
                if (state.latest == null && state.error) add(R.string.hint_error)
            }
            hints.forEach { HintCard(stringResource(it)) }

            Text(
                stringResource(R.string.history_title),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { heading() },
            )
            HistoryChart(points = state.history?.points.orEmpty(), thresholds = thresholds, now = now)
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
private fun TrafficCircle(level: Level, value: String?) {
    val unit = stringResource(R.string.unit)
    val description = "${value ?: stringResource(R.string.value_missing)} $unit, ${levelText(level)}"
    Box(
        modifier = Modifier
            .size(220.dp)
            .background(levelColor(level), CircleShape)
            .clearAndSetSemantics { contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                value ?: stringResource(R.string.value_missing),
                color = onLevelColor(level),
                fontSize = 64.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(unit, color = onLevelColor(level), style = MaterialTheme.typography.titleMedium)
        }
    }
}

@Composable
private fun IntensityRow(reading: ZoneReading?) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        ValueCard(
            label = stringResource(R.string.consumption),
            value = formatValue(reading?.consumption),
            explanation = stringResource(R.string.consumption_explained),
            modifier = Modifier.weight(1f),
        )
        ValueCard(
            label = stringResource(R.string.production),
            value = formatValue(reading?.production),
            explanation = stringResource(R.string.production_explained),
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun ValueCard(label: String, value: String?, explanation: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier) {
        Column(Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.labelLarge)
            Text(
                "${value ?: stringResource(R.string.value_missing)} ${stringResource(R.string.unit)}",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Text(explanation, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun HintCard(text: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer,
            contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        ),
    ) {
        Text(text, modifier = Modifier.padding(12.dp), style = MaterialTheme.typography.bodyMedium)
    }
}
