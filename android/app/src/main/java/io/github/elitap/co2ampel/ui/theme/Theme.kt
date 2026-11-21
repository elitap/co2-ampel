package io.github.elitap.co2ampel.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import io.github.elitap.co2ampel.domain.Level

private val LightScheme = lightColorScheme(
    primary = Color(0xFF2E6B45),
    onPrimary = Color.White,
    background = Color(0xFFFBFEFB),
    surface = Color(0xFFFBFEFB),
)

private val DarkScheme = darkColorScheme(
    primary = Color(0xFF94D5A8),
    onPrimary = Color(0xFF00391C),
    background = Color(0xFF191C1A),
    surface = Color(0xFF191C1A),
)

@Composable
fun Co2Theme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val scheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val ctx = LocalContext.current
            if (dark) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
        }
        dark -> DarkScheme
        else -> LightScheme
    }
    MaterialTheme(colorScheme = scheme, content = content)
}

/** Ampelfarben; Kontrast der Beschriftung (onLevelColor) jeweils >= 4.5:1 (WCAG AA). */
fun levelColor(level: Level): Color = when (level) {
    Level.GREEN -> Color(0xFF1E7E34)
    Level.YELLOW -> Color(0xFFF2C200)
    Level.RED -> Color(0xFFC62828)
    Level.UNKNOWN -> Color(0xFF757575)
}

fun onLevelColor(level: Level): Color = if (level == Level.YELLOW) Color(0xFF1A1A1A) else Color.White
