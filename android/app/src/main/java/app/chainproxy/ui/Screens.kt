package app.chainproxy.ui

import android.app.StatusBarManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.graphics.drawable.Icon
import android.os.Build
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Apps
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.FactCheck
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Login
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.filled.ViewQuilt
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.chainproxy.BuildConfig
import app.chainproxy.R
import app.chainproxy.chain.ChainConfig
import app.chainproxy.session.AppState
import app.chainproxy.session.ConfigStore
import app.chainproxy.update.UpdateChecker
import app.chainproxy.vpn.ChainTileService
import app.chainproxy.vpn.Phase
import app.chainproxy.vpn.VpnState
import kotlinx.coroutines.launch

@Composable
private fun SectionCard(icon: ImageVector, title: String, subtitle: String? = null, content: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.size(36.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer), contentAlignment = Alignment.Center) {
                    Icon(icon, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
                }
                Column {
                    Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            content()
        }
    }
}

/** The big round power button: grey ring when off, spinner while working, solid green when connected. */
@Composable
private fun PowerButton(phase: Phase, onClick: () -> Unit) {
    val busy = phase == Phase.Starting || phase == Phase.Stopping
    val on = phase == Phase.Running
    val fill by animateColorAsState(if (on) Ok else MaterialTheme.colorScheme.surface, label = "fill")
    val ring = when { on -> Ok; phase == Phase.Failed -> Bad; else -> MaterialTheme.colorScheme.outline }
    Surface(onClick = onClick, shape = CircleShape, color = fill, shadowElevation = if (on) 10.dp else 4.dp,
        border = BorderStroke(3.dp, ring), modifier = Modifier.size(148.dp)) {
        Box(contentAlignment = Alignment.Center) {
            if (busy) CircularProgressIndicator(Modifier.size(56.dp), strokeWidth = 4.dp)
            else Icon(Icons.Filled.PowerSettingsNew, null, modifier = Modifier.size(64.dp),
                tint = if (on) Color.White else if (phase == Phase.Failed) Bad else MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable
fun HomeScreen(onToggle: () -> Unit, onAction: (String) -> Unit) {
    val ctx = LocalContext.current
    val status by VpnState.status.collectAsState()
    val summary by AppState.summary.collectAsState()
    val lantern by AppState.lantern.collectAsState()
    val rows by AppState.rows.collectAsState()
    val running = status.phase == Phase.Running
    val active = rows.firstOrNull { it.active }
    var tileNote by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Box(Modifier.fillMaxWidth().background(Brush.verticalGradient(listOf(
            if (running) Ok.copy(alpha = 0.22f) else MaterialTheme.colorScheme.primary.copy(alpha = 0.16f), Color.Transparent)))
            .padding(top = 40.dp, bottom = 24.dp), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(14.dp)) {
                PowerButton(status.phase, onToggle)
                Text(stringResource(when (status.phase) {
                    Phase.Running -> R.string.hero_on
                    Phase.Starting, Phase.Stopping -> R.string.hero_busy
                    Phase.Failed -> R.string.hero_failed
                    Phase.Stopped -> R.string.hero_idle
                }), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                Text(stringResource(when (status.phase) {
                    Phase.Running -> R.string.state_running
                    Phase.Starting -> R.string.state_starting
                    Phase.Stopping -> R.string.state_stopping
                    Phase.Failed -> R.string.state_failed
                    Phase.Stopped -> R.string.state_stopped
                }), color = when (status.phase) { Phase.Running -> Ok; Phase.Failed -> Bad; else -> MaterialTheme.colorScheme.onSurfaceVariant },
                    style = MaterialTheme.typography.labelLarge)
            }
        }
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            if (status.message.isNotEmpty()) Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.10f)),
                shape = MaterialTheme.shapes.medium) {
                Text(status.message, Modifier.padding(14.dp), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
            }
            if (running && active != null) SectionCard(Icons.Filled.Dns, active.source, stringResource(R.string.exit_label)) {
                Text(active.label, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                if (summary.isNotEmpty()) Text(summary.substringAfter("exit: ", summary), style = MaterialTheme.typography.bodyMedium)
                Text("${active.delayMs.toInt()} ms" + if (lantern != "off") "   |   ${stringResource(R.string.lantern_label)}: $lantern" else "",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                FilledTonalButton(onClick = { onAction("prev") }, enabled = running, modifier = Modifier.weight(1f), contentPadding = PaddingValues(8.dp)) {
                    Icon(Icons.Filled.SkipPrevious, null, Modifier.size(18.dp)); Spacer(Modifier.size(4.dp)); Text(stringResource(R.string.prev_route), maxLines = 1)
                }
                FilledTonalButton(onClick = { onAction("next") }, enabled = running, modifier = Modifier.weight(1f), contentPadding = PaddingValues(8.dp)) {
                    Icon(Icons.Filled.SkipNext, null, Modifier.size(18.dp)); Spacer(Modifier.size(4.dp)); Text(stringResource(R.string.next_route), maxLines = 1)
                }
                FilledTonalButton(onClick = { onAction("rescan") }, enabled = running, modifier = Modifier.weight(1f), contentPadding = PaddingValues(8.dp)) {
                    Icon(Icons.Filled.Refresh, null, Modifier.size(18.dp)); Spacer(Modifier.size(4.dp)); Text(stringResource(R.string.rescan), maxLines = 1)
                }
            }
            SectionCard(Icons.Filled.ViewQuilt, stringResource(R.string.quick_settings), stringResource(R.string.tile_hint)) {
                if (tileNote.isNotEmpty()) Text(tileNote, style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = { tileNote = requestTile(ctx) }, Modifier.fillMaxWidth()) { Text(stringResource(R.string.add_tile)) }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

/** Android 13+ can ask the system to add the tile; older versions get a hint on how to do it by hand. */
private fun requestTile(ctx: Context): String {
    if (Build.VERSION.SDK_INT < 33) return ctx.getString(R.string.tile_hint)
    return try {
        ctx.getSystemService(StatusBarManager::class.java).requestAddTileService(
            ComponentName(ctx, ChainTileService::class.java), "Chain Proxy", Icon.createWithResource(ctx, R.drawable.ic_launcher),
            ctx.mainExecutor) {}
        ctx.getString(R.string.tile_requested)
    } catch (e: Exception) { ctx.getString(R.string.tile_hint) }
}

@Composable
fun RoutesScreen(onPick: (Int) -> Unit) {
    val rows by AppState.rows.collectAsState()
    if (rows.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(stringResource(R.string.no_routes), color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center, modifier = Modifier.padding(32.dp))
        }
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text(stringResource(R.string.tap_to_use), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        itemsIndexed(rows) { i, r ->
            Card(Modifier.fillMaxWidth().clickable { onPick(i) }, shape = MaterialTheme.shapes.medium,
                border = if (r.active) BorderStroke(2.dp, Ok) else null,
                colors = CardDefaults.cardColors(containerColor = if (r.active) OkSoft.copy(alpha = if (MaterialTheme.colorScheme.background.red < 0.5f) 0.12f else 1f)
                    else MaterialTheme.colorScheme.surface)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Text("${i + 1}.  ${r.source}", fontWeight = FontWeight.SemiBold)
                        Text(if (r.active) stringResource(R.string.route_active) else "${r.delayMs.toInt()} ms",
                            color = if (r.active) Ok else MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelLarge)
                    }
                    Text(r.label, fontFamily = FontFamily.Monospace, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    r.rejected?.let { Text(stringResource(R.string.route_rejected, it), color = MaterialTheme.colorScheme.error, fontSize = 12.sp) }
                }
            }
        }
    }
}

@Composable
fun LogScreen() {
    val lines by AppState.log.collectAsState()
    val ctx = LocalContext.current
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        FilledTonalButton(onClick = {
            (ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("log", lines.joinToString("\n")))
        }) { Icon(Icons.Filled.ContentCopy, null, Modifier.size(18.dp)); Spacer(Modifier.size(8.dp)); Text(stringResource(R.string.copy_log)) }
        Card(Modifier.fillMaxSize(), shape = MaterialTheme.shapes.medium, colors = CardDefaults.cardColors(containerColor = Color(0xFF0F172A))) {
            LazyColumn(Modifier.fillMaxSize().padding(12.dp)) {
                itemsIndexed(lines) { _, l -> Text(l, fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = Color(0xFFD1D9E6)) }
            }
        }
    }
}

private fun lines(s: String) = s.lines().map { it.trim() }.filter { it.isNotEmpty() }
private fun csv(s: String) = s.split(',', '\n').map { it.trim() }.filter { it.isNotEmpty() }

@Composable
fun SettingsScreen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var cfg by remember { mutableStateOf(ConfigStore.load(ctx)) }
    var saved by remember { mutableStateOf(false) }
    var picking by remember { mutableStateOf(false) }
    var updateText by remember { mutableStateOf("") }
    var updateInfo by remember { mutableStateOf<UpdateChecker.Info?>(null) }
    fun edit(c: ChainConfig) { cfg = c; saved = false }

    if (picking) {
        AppPicker(cfg.splitApps.toSet(), onDone = { edit(cfg.copy(splitApps = it.sorted())); picking = false })
        return
    }
    val full = Modifier.fillMaxWidth()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        SectionCard(Icons.Filled.Login, stringResource(R.string.section_first), stringResource(R.string.section_first_desc)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(cfg.lanternEnabled, { edit(cfg.copy(lanternEnabled = it)) })
                Text(stringResource(R.string.use_lantern), Modifier.padding(start = 12.dp), style = MaterialTheme.typography.bodyMedium)
            }
            OutlinedTextField(cfg.firstSubscription, { edit(cfg.copy(firstSubscription = it)) }, full,
                label = { Text(stringResource(R.string.first_sub)) }, singleLine = true, shape = MaterialTheme.shapes.medium)
            OutlinedTextField(cfg.firstProfiles, { edit(cfg.copy(firstProfiles = it)) }, full,
                label = { Text(stringResource(R.string.first_profiles)) }, minLines = 2, maxLines = 5, shape = MaterialTheme.shapes.medium)
        }
        SectionCard(Icons.Filled.Logout, stringResource(R.string.section_exit), stringResource(R.string.section_exit_desc)) {
            OutlinedTextField(cfg.exitSubscription, { edit(cfg.copy(exitSubscription = it)) }, full,
                label = { Text(stringResource(R.string.exit_sub)) }, singleLine = true, shape = MaterialTheme.shapes.medium)
            OutlinedTextField(cfg.exitProfiles, { edit(cfg.copy(exitProfiles = it)) }, full,
                label = { Text(stringResource(R.string.exit_profiles)) }, minLines = 2, maxLines = 5, shape = MaterialTheme.shapes.medium)
        }
        SectionCard(Icons.Filled.FactCheck, stringResource(R.string.settings_filters), stringResource(R.string.section_checks_desc)) {
            OutlinedTextField(cfg.strictUrls.joinToString("\n"), { edit(cfg.copy(strictUrls = lines(it))) }, full,
                label = { Text(stringResource(R.string.strict_sites)) }, minLines = 1, maxLines = 4, shape = MaterialTheme.shapes.medium)
            OutlinedTextField(cfg.blockedCountries.joinToString(", "), { edit(cfg.copy(blockedCountries = csv(it).map(String::uppercase))) },
                full, label = { Text(stringResource(R.string.blocked_countries)) }, singleLine = true, shape = MaterialTheme.shapes.medium)
            OutlinedTextField(cfg.directSuffixes.joinToString(", "), { edit(cfg.copy(directSuffixes = csv(it))) },
                full, label = { Text(stringResource(R.string.direct_sites)) }, singleLine = true, shape = MaterialTheme.shapes.medium)
        }
        SectionCard(Icons.Filled.Apps, stringResource(R.string.settings_apps), stringResource(R.string.section_apps_desc)) {
            for ((mode, label) in listOf("all" to R.string.split_all, "include" to R.string.split_include, "exclude" to R.string.split_exclude)) {
                Row(full.selectable(cfg.splitMode == mode, onClick = { edit(cfg.copy(splitMode = mode)) }), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(cfg.splitMode == mode, onClick = { edit(cfg.copy(splitMode = mode)) })
                    Text(stringResource(label), style = MaterialTheme.typography.bodyMedium)
                }
            }
            if (cfg.splitMode != "all") OutlinedButton(onClick = { picking = true }) { Text(stringResource(R.string.choose_apps, cfg.splitApps.size)) }
        }
        Button(onClick = { ConfigStore.save(ctx, cfg); saved = true }, full.height(52.dp), shape = MaterialTheme.shapes.large) { Text(stringResource(R.string.save)) }
        if (saved) Text(stringResource(R.string.saved), color = Ok, style = MaterialTheme.typography.bodyMedium)
        SectionCard(Icons.Filled.Info, stringResource(R.string.about), "Chain Proxy ${BuildConfig.VERSION_NAME}") {
            Text(stringResource(R.string.license_note), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedButton(onClick = {
                scope.launch {
                    updateText = "..."
                    updateInfo = null
                    UpdateChecker.check(cfg.updateRepo, BuildConfig.VERSION_NAME).fold(
                        { info ->
                            updateInfo = info
                            updateText = if (info == null) ctx.getString(R.string.update_none) else ctx.getString(R.string.update_found, info.version)
                        },
                        { updateText = ctx.getString(R.string.update_failed, it.message ?: it.javaClass.simpleName) })
                }
            }) { Text(stringResource(R.string.update_check)) }
            if (updateText.isNotEmpty()) Text(updateText, style = MaterialTheme.typography.bodyMedium)
            updateInfo?.let { info ->
                Button(onClick = { scope.launch { UpdateChecker.downloadAndInstall(ctx, info) { updateText = it } } }) { Text(stringResource(R.string.update_install)) }
            }
        }
    }
}
