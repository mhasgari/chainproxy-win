package app.chainproxy.vpn

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class Phase { Stopped, Starting, Running, Stopping, Failed }

data class VpnStatus(val phase: Phase = Phase.Stopped, val message: String = "")

/** Process-wide VPN state: the service writes it, the UI observes it (both live in the same process). */
object VpnState {
    private val _status = MutableStateFlow(VpnStatus())
    val status: StateFlow<VpnStatus> = _status.asStateFlow()

    fun set(phase: Phase, message: String = "") {
        _status.value = VpnStatus(phase, message)
    }
}
