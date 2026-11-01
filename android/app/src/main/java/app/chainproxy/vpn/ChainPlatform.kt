package app.chainproxy.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.VpnService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.util.Log
import io.nekohasekai.libbox.BridgeOptions
import io.nekohasekai.libbox.BridgeSession
import io.nekohasekai.libbox.ConnectionOwner
import io.nekohasekai.libbox.InterfaceUpdateListener
import io.nekohasekai.libbox.LocalDNSTransport
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.libbox.NeighborUpdateListener
import io.nekohasekai.libbox.NetworkInterfaceIterator
import io.nekohasekai.libbox.Notification
import io.nekohasekai.libbox.PlatformInterface
import io.nekohasekai.libbox.PlatformUser
import io.nekohasekai.libbox.ShellSession
import io.nekohasekai.libbox.StringIterator
import io.nekohasekai.libbox.TunOptions
import io.nekohasekai.libbox.WIFIState
import java.net.NetworkInterface as JNetworkInterface

private const val TAG = "ChainPlatform"

/**
 * What libbox (sing-box) needs from Android: a TUN device from [VpnService], socket protection and the
 * default network. Everything else of the platform contract is not used and answers "unsupported".
 */
class ChainPlatform(private val service: VpnService, private val ownPackage: String) : PlatformInterface {
    private val cm = service.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private var callback: ConnectivityManager.NetworkCallback? = null

    private var tun: ParcelFileDescriptor? = null

    @Volatile
    var tunName: String = ""
        private set

    // ---- TUN -------------------------------------------------------------------------------
    override fun openTun(options: TunOptions): Int {
        if (VpnService.prepare(service) != null) throw SecurityException("VPN permission is not granted")
        val b = service.Builder().setSession("Chain Proxy").setMtu(options.mtu)
        for (p in options.inet4Address.toList()) b.addAddress(p.address(), p.prefix())
        for (p in options.inet6Address.toList()) b.addAddress(p.address(), p.prefix())
        if (options.autoRoute) {
            val dns = options.dnsServerAddress.next()
            b.addDnsServer(dns)
            val r4 = options.inet4RouteAddress.toList()
            if (r4.isNotEmpty()) r4.forEach { b.addRoute(it.address(), it.prefix()) } else b.addRoute("0.0.0.0", 0)
            val r6 = options.inet6RouteAddress.toList()
            if (r6.isNotEmpty()) r6.forEach { b.addRoute(it.address(), it.prefix()) } else b.addRoute("::", 0)
        }
        // The app itself (libbox sockets, the Lantern engine process) must never go through its own tunnel.
        val include = options.includePackage.toList()
        if (include.isNotEmpty()) {
            include.filter { it != ownPackage }.forEach { runCatching { b.addAllowedApplication(it) } }
        } else {
            runCatching { b.addDisallowedApplication(ownPackage) }
            options.excludePackage.toList().forEach { runCatching { b.addDisallowedApplication(it) } }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) b.setMetered(false)
        val pfd = b.establish() ?: throw IllegalStateException("the system refused to create the VPN interface")
        tun?.close()
        tun = pfd              // libbox does not close the descriptor: the service does, in [close]
        return pfd.fd
    }

    /** Releases the TUN device; without this the interface (and the VPN key icon) outlive the core. */
    fun close() {
        runCatching { tun?.close() }
        tun = null
    }

    override fun usePlatformAutoDetectInterfaceControl() = true
    override fun autoDetectInterfaceControl(fd: Int) {
        if (!service.protect(fd)) Log.w(TAG, "protect($fd) failed")
    }

    override fun registerMyInterface(name: String) {
        tunName = name
    }

    // ---- default network ------------------------------------------------------------------
    override fun startDefaultInterfaceMonitor(listener: InterfaceUpdateListener) {
        val cb = object : ConnectivityManager.NetworkCallback() {
            private fun publish(network: Network?) {
                val props = network?.let { cm.getLinkProperties(it) }
                val name = props?.interfaceName
                if (name == null) {
                    listener.updateDefaultInterface("", -1, false, false)
                    return
                }
                val index = runCatching { JNetworkInterface.getByName(name)?.index }.getOrNull() ?: -1
                val caps = network.let { cm.getNetworkCapabilities(it) }
                val expensive = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED) == false
                Log.i(TAG, "default interface: $name index=$index expensive=$expensive")
                listener.updateDefaultInterface(name, index, expensive, false)
            }

            override fun onAvailable(network: Network) = publish(network)
            override fun onLost(network: Network) = publish(null)
            override fun onLinkPropertiesChanged(network: Network, p: android.net.LinkProperties) = publish(network)
        }
        callback = cb
        // Not registerDefaultNetworkCallback: once our VPN is up IT is the default network, but sing-box needs the
        // underlying (non-VPN) one. A plain request already carries NOT_VPN; the system picks the best match.
        val request = NetworkRequest.Builder().addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            cm.registerBestMatchingNetworkCallback(request, cb, Handler(Looper.getMainLooper()))
        } else {
            cm.requestNetwork(request, cb)
        }
    }

    override fun closeDefaultInterfaceMonitor(listener: InterfaceUpdateListener) {
        callback?.let { runCatching { cm.unregisterNetworkCallback(it) } }
        callback = null
    }

    override fun getInterfaces(): NetworkInterfaceIterator {
        val out = ArrayList<io.nekohasekai.libbox.NetworkInterface>()
        val all = runCatching { JNetworkInterface.getNetworkInterfaces()?.toList() }.getOrNull().orEmpty()
        for (ni in all) {
            if (!ni.isUp) continue
            out += io.nekohasekai.libbox.NetworkInterface().apply {
                name = ni.name
                index = ni.index
                mtu = runCatching { ni.mtu }.getOrDefault(1500)
                addresses = StringListIterator(ni.interfaceAddresses.map { "${it.address.hostAddress?.substringBefore('%')}/${it.networkPrefixLength}" })
                type = when {
                    ni.name.startsWith("wlan") -> Libbox.InterfaceTypeWIFI
                    ni.name.startsWith("rmnet") || ni.name.startsWith("ccmni") -> Libbox.InterfaceTypeCellular
                    ni.name.startsWith("eth") -> Libbox.InterfaceTypeEthernet
                    else -> Libbox.InterfaceTypeOther
                }
                // net.Flags bits on the Go side: up 1, broadcast 2, loopback 4, pointToPoint 8, multicast 16, running 32
                flags = 1 or 32 or (if (ni.isLoopback) 4 else 2) or (if (ni.isPointToPoint) 8 else 0) or
                    (if (runCatching { ni.supportsMulticast() }.getOrDefault(false)) 16 else 0)
                dnsServer = StringListIterator(emptyList())
                gateway = StringListIterator(emptyList())
                metered = false
            }
        }
        Log.i(TAG, "interfaces: " + out.joinToString { "${it.name}#${it.index}" })
        return InterfaceIterator(out)
    }

    // ---- not used --------------------------------------------------------------------------
    override fun underNetworkExtension() = false
    override fun includeAllNetworks() = false
    override fun usePlatformBridge() = false
    override fun usePlatformShell() = false
    override fun createBridge(options: BridgeOptions): BridgeSession = throw UnsupportedOperationException()
    override fun checkPlatformShell() = throw UnsupportedOperationException()
    override fun openShellSession(user: PlatformUser?, a: String?, b: StringIterator?, c: String?, d: Int, e: Int) =
        throw UnsupportedOperationException()
    override fun lookupUser(name: String): PlatformUser = throw UnsupportedOperationException()
    override fun lookupSFTPServer(): String = throw UnsupportedOperationException()
    override fun readSystemSSHHostKey(): String = throw UnsupportedOperationException()
    override fun findConnectionOwner(p: Int, sa: String, sp: Int, da: String, dp: Int): ConnectionOwner =
        throw UnsupportedOperationException()
    override fun localDNSTransport(): LocalDNSTransport? = null
    override fun readWIFIState(): WIFIState? = null
    override fun clearDNSCache() {}
    override fun sendNotification(n: Notification) {}
    override fun cancelNotification(id: String, n: Int) {}
    override fun startNeighborMonitor(l: NeighborUpdateListener) {}
    override fun closeNeighborMonitor(l: NeighborUpdateListener) {}
    override fun tailscaleHostname() = ""
}
