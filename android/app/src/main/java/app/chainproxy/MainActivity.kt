package app.chainproxy

import android.Manifest
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import app.chainproxy.ui.HomeScreen
import app.chainproxy.ui.LogScreen
import app.chainproxy.ui.RoutesScreen
import app.chainproxy.ui.SettingsScreen
import app.chainproxy.vpn.ChainVpnService
import app.chainproxy.vpn.Phase
import app.chainproxy.vpn.VpnState

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleDebugIntent(intent)
        enableEdgeToEdge()
        setContent {
            app.chainproxy.ui.ChainTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    val status by VpnState.status.collectAsState()
                    var tab by remember { mutableIntStateOf(0) }
                    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
                    val askVpn = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
                        if (it.resultCode == RESULT_OK) startVpn()
                    }
                    val tabs = listOf(
                        Triple(R.string.tab_home, Icons.Filled.Home, 0), Triple(R.string.tab_routes, Icons.Filled.List, 1),
                        Triple(R.string.tab_settings, Icons.Filled.Settings, 2), Triple(R.string.tab_log, Icons.Filled.Info, 3))
                    Scaffold(bottomBar = {
                        NavigationBar {
                            tabs.forEach { (label, icon, i) ->
                                NavigationBarItem(tab == i, { tab = i }, { Icon(icon, null) }, label = { Text(stringResource(label)) })
                            }
                        }
                    }) { pad ->
                        androidx.compose.foundation.layout.Box(Modifier.padding(pad)) {
                            when (tab) {
                                0 -> HomeScreen(onToggle = {
                                    if (status.phase == Phase.Running || status.phase == Phase.Starting) {
                                        startService(Intent(this@MainActivity, ChainVpnService::class.java).setAction(ChainVpnService.ACTION_STOP))
                                    } else {
                                        if (Build.VERSION.SDK_INT >= 33) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                                        val need = VpnService.prepare(this@MainActivity)
                                        if (need != null) askVpn.launch(need) else startVpn()
                                    }
                                }, onAction = { act ->
                                    startService(Intent(this@MainActivity, ChainVpnService::class.java).setAction(when (act) {
                                        "next" -> ChainVpnService.ACTION_NEXT; "prev" -> ChainVpnService.ACTION_PREV; else -> ChainVpnService.ACTION_RESCAN }))
                                })
                                1 -> RoutesScreen(onPick = { i ->
                                    startService(Intent(this@MainActivity, ChainVpnService::class.java)
                                        .setAction(ChainVpnService.ACTION_GOTO).putExtra(ChainVpnService.EXTRA_INDEX, i))
                                })
                                2 -> SettingsScreen()
                                else -> LogScreen()
                            }
                        }
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleDebugIntent(intent)
    }

    /** adb hook for the emulator tests (debug builds only): am start -n .../.MainActivity --es debug_action start|stop|... */
    private fun handleDebugIntent(intent: Intent?) {
        if (!BuildConfig.DEBUG) return
        when (intent?.getStringExtra("debug_action")) {
            "start" -> startVpn()
            "start_config" -> startForegroundService(Intent(this, ChainVpnService::class.java)
                .setAction(ChainVpnService.ACTION_START).putExtra(ChainVpnService.EXTRA_CONFIG, filesDir.resolve("config.json").path))
            "stop" -> startService(Intent(this, ChainVpnService::class.java).setAction(ChainVpnService.ACTION_STOP))
            "next", "prev", "rescan" -> startService(Intent(this, ChainVpnService::class.java).setAction(
                when (intent.getStringExtra("debug_action")) { "next" -> ChainVpnService.ACTION_NEXT; "prev" -> ChainVpnService.ACTION_PREV; else -> ChainVpnService.ACTION_RESCAN }))
        }
    }

    private fun startVpn() {
        startForegroundService(Intent(this, ChainVpnService::class.java).setAction(ChainVpnService.ACTION_START))
    }
}
