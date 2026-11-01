package app.chainproxy.vpn

import io.nekohasekai.libbox.NetworkInterface
import io.nekohasekai.libbox.NetworkInterfaceIterator
import io.nekohasekai.libbox.RoutePrefix
import io.nekohasekai.libbox.RoutePrefixIterator
import io.nekohasekai.libbox.StringIterator

/** Plain Kotlin lists handed to libbox through its iterator interfaces. */
class StringListIterator(private val items: List<String>) : StringIterator {
    private var i = 0
    override fun hasNext() = i < items.size
    override fun len() = items.size
    override fun next(): String = items[i++]
}

fun StringIterator?.toList(): List<String> {
    val out = ArrayList<String>()
    if (this == null) return out
    while (hasNext()) out += next()
    return out
}

fun RoutePrefixIterator?.toList(): List<RoutePrefix> {
    val out = ArrayList<RoutePrefix>()
    if (this == null) return out
    while (hasNext()) out += next()
    return out
}

class InterfaceIterator(private val items: List<NetworkInterface>) : NetworkInterfaceIterator {
    private var i = 0
    override fun hasNext() = i < items.size
    override fun next(): NetworkInterface = items[i++]
}
