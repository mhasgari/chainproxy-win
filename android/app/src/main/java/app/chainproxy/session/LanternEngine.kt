package app.chainproxy.session

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import app.chainproxy.chain.Node
import app.chainproxy.chain.lanternNode
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File
import java.net.InetSocketAddress
import java.net.Socket

/**
 * The Lantern engine (libchainlantern.so, a Go executable stored as a native library) as a child process.
 * It prints "CHAINLANTERN READY|STATUS|ERROR ..." lines and exits when its stdin closes.
 */
class LanternEngine(private val ctx: Context, private val port: Int) {
    @Volatile private var proc: Process? = null
    @Volatile var ready = false; private set
    @Volatile var status = "stopped"; private set
    @Volatile var error = ""; private set

    fun node(): Node = lanternNode(port)

    /** Go finds no resolv.conf on Android; give it the DNS server of the real (non-VPN) network. */
    private fun dnsServer(): String {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        for (n in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(n) ?: continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) || caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue
            val dns = cm.getLinkProperties(n)?.dnsServers?.firstOrNull { it is java.net.Inet4Address }
            if (dns != null) return "${dns.hostAddress}:53"
        }
        return "1.1.1.1:53"
    }

    fun start(scope: CoroutineScope) {
        val exe = File(ctx.applicationInfo.nativeLibraryDir, "libchainlantern.so")
        if (!exe.exists()) { error = "engine missing for this CPU"; status = "unavailable"; return }
        val data = File(ctx.filesDir, "lantern").apply { mkdirs() }
        ready = false; error = ""; status = "starting"
        val p = ProcessBuilder(exe.path, "-dns", dnsServer(), "-data-path", data.path, "-listen", "127.0.0.1:$port", "-log-level", "warn")
            .redirectErrorStream(true).start()
        proc = p
        scope.launch(Dispatchers.IO) {
            p.inputStream.bufferedReader().forEachLine { line ->
                if (!line.startsWith("CHAINLANTERN ")) return@forEachLine
                val body = line.substring(13)
                val kind = body.substringBefore(' ')
                val rest = body.substringAfter(' ', "")
                when (kind) {
                    "READY" -> { ready = true; status = "connected" }
                    "STATUS" -> { status = rest; if (rest != "connected") ready = false }
                    "ERROR" -> error = rest
                }
                AppState.setLantern(if (ready) "connected" else status)
            }
            ready = false
            if (status != "unavailable") status = "stopped"
            AppState.setLantern(status)
        }
    }

    private fun portOpen(): Boolean = try {
        Socket().use { it.connect(InetSocketAddress("127.0.0.1", port), 500); true }
    } catch (e: Exception) { false }

    /** True once connected and the SOCKS port answers; false on failure or timeout (error is set). */
    suspend fun waitReady(timeoutSec: Int): Boolean {
        val end = System.currentTimeMillis() + timeoutSec * 1000L
        while (System.currentTimeMillis() < end) {
            if (ready && portOpen()) return true
            val p = proc
            if (status == "unavailable" || p == null || !p.isAlive) break
            delay(400)
        }
        if (error.isEmpty()) error = if (proc?.isAlive == true) "did not connect in time" else "the engine exited"
        return false
    }

    fun stop() {
        val p = proc ?: return
        proc = null
        ready = false
        runCatching { p.outputStream.close() }                 // the engine exits when its stdin closes
        Thread {
            if (!p.waitFor(8, java.util.concurrent.TimeUnit.SECONDS)) p.destroyForcibly()
        }.start()
        status = "stopped"
        AppState.setLantern("off")
    }
}
