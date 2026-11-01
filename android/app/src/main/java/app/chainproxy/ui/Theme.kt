package app.chainproxy.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.shape.RoundedCornerShape

/** One fixed palette (not the wallpaper colours) so the app looks the same on every phone. */
val Ink = Color(0xFF0F172A)
val Brand = Color(0xFF2F6BFF)
val BrandDeep = Color(0xFF1D4ED8)
val Ok = Color(0xFF16A34A)
val OkSoft = Color(0xFFDCFCE7)
val Warn = Color(0xFFD97706)
val Bad = Color(0xFFDC2626)

private val Light = lightColorScheme(
    primary = Brand, onPrimary = Color.White, primaryContainer = Color(0xFFE3ECFF), onPrimaryContainer = Color(0xFF0B2A78),
    secondary = Color(0xFF475569), surface = Color.White, onSurface = Ink, background = Color(0xFFF4F6FB), onBackground = Ink,
    surfaceVariant = Color(0xFFEAEFF8), onSurfaceVariant = Color(0xFF475569), outline = Color(0xFFCBD5E1), error = Bad,
)
private val Dark = darkColorScheme(
    primary = Color(0xFF7BA3FF), onPrimary = Color(0xFF0A1F5C), primaryContainer = Color(0xFF1B2F6B), onPrimaryContainer = Color(0xFFDCE6FF),
    secondary = Color(0xFF94A3B8), surface = Color(0xFF151B2B), onSurface = Color(0xFFE5EAF5), background = Color(0xFF0C1120), onBackground = Color(0xFFE5EAF5),
    surfaceVariant = Color(0xFF1E2640), onSurfaceVariant = Color(0xFFA7B3CC), outline = Color(0xFF334155), error = Color(0xFFF87171),
)

@Composable
fun ChainTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) Dark else Light,
        shapes = Shapes(small = RoundedCornerShape(10.dp), medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(24.dp)),
        content = content,
    )
}
