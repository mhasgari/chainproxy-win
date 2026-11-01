package app.chainproxy.vpn

import android.content.Intent
import android.net.VpnService
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import app.chainproxy.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** Quick Settings tile: tap to connect / disconnect (opens the app once if the VPN permission was never granted). */
class ChainTileService : TileService() {
    private var scope: CoroutineScope? = null

    override fun onStartListening() {
        val s = CoroutineScope(Dispatchers.Main + Job())
        scope = s
        s.launch { VpnState.status.collect { render(it.phase) } }
    }

    override fun onStopListening() {
        scope?.cancel()
        scope = null
    }

    private fun render(phase: Phase) {
        val tile = qsTile ?: return
        tile.state = when (phase) {
            Phase.Running -> Tile.STATE_ACTIVE
            Phase.Starting, Phase.Stopping -> Tile.STATE_UNAVAILABLE
            else -> Tile.STATE_INACTIVE
        }
        tile.label = "Chain Proxy"
        tile.updateTile()
    }

    @Suppress("DEPRECATION")
    override fun onClick() {
        when (VpnState.status.value.phase) {
            Phase.Running -> startService(Intent(this, ChainVpnService::class.java).setAction(ChainVpnService.ACTION_STOP))
            Phase.Stopped, Phase.Failed -> {
                if (VpnService.prepare(this) != null) {
                    startActivityAndCollapse(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                } else {
                    startForegroundService(Intent(this, ChainVpnService::class.java).setAction(ChainVpnService.ACTION_START))
                }
            }
            else -> {}
        }
    }
}
