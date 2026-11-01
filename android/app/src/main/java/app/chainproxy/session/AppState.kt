package app.chainproxy.session

import android.content.Context
import app.chainproxy.chain.ChainConfig
import app.chainproxy.chain.RouteRow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File

/** Process-wide state the UI, the notification and the tile observe; the session writes it. */
object AppState {
    private val _rows = MutableStateFlow<List<RouteRow>>(emptyList())
    val rows: StateFlow<List<RouteRow>> = _rows.asStateFlow()
    private val _summary = MutableStateFlow("")
    /** One line about the active route: "[2/9] A1:x -> B3:y  420ms  exit: 1.2.3.4 DE ...". */
    val summary: StateFlow<String> = _summary.asStateFlow()
    private val _log = MutableStateFlow<List<String>>(emptyList())
    val log: StateFlow<List<String>> = _log.asStateFlow()
    private val _lantern = MutableStateFlow("off")
    val lantern: StateFlow<String> = _lantern.asStateFlow()

    fun setRows(r: List<RouteRow>) { _rows.value = r }
    fun setSummary(s: String) { _summary.value = s }
    fun setLantern(s: String) { _lantern.value = s }

    @Synchronized
    fun log(line: String) {
        val stamp = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US).format(java.util.Date())
        _log.value = (_log.value + "$stamp $line").takeLast(400)
        android.util.Log.i("ChainSession", line)
    }

    fun clearLog() { _log.value = emptyList() }

    fun clear() { _rows.value = emptyList(); _summary.value = ""; _lantern.value = "off" }
}

/** config.json in the app's private files directory (same keys as the desktop config.json). */
object ConfigStore {
    private fun file(ctx: Context) = File(ctx.filesDir, "chain-config.json")
    fun load(ctx: Context): ChainConfig = ChainConfig.fromJson(runCatching { file(ctx).readText() }.getOrNull())
    fun save(ctx: Context, cfg: ChainConfig) { file(ctx).writeText(cfg.toJson()) }
}
