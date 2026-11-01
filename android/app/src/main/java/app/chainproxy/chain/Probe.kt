package app.chainproxy.chain

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import java.net.InetSocketAddress
import java.net.Socket

/** Milliseconds a TCP connect to the node takes, null when it fails. UDP-only nodes (hysteria2) cannot be probed. */
suspend fun tcpMs(ob: JsonObject, timeoutSec: Double): Double? {
    if (ob["type"]?.jsonPrimitive?.content == "hysteria2") return 500.0
    return withContext(Dispatchers.IO) {
        val t0 = System.nanoTime()
        try {
            Socket().use { it.connect(InetSocketAddress(ob["server"]!!.jsonPrimitive.content, ob["server_port"]!!.jsonPrimitive.int), (timeoutSec * 1000).toInt()) }
            (System.nanoTime() - t0) / 1e6
        } catch (e: Exception) {
            null
        }
    }
}

/**
 * Port of chain.pick: the [k] fastest reachable nodes, tagged prefix+number. When direct probing is filtered (no node
 * answers) all nodes are kept and the end-to-end test decides. [validator] drops nodes the core refuses to load.
 * [extraUnreachable] (Android): that many nodes whose direct probe FAILED are kept after the reachable ones. A node behind
 * a first hop (Lantern) is dialled from that hop's server, so the phone not reaching it directly says nothing about the chain.
 * [note] receives (reachable, kept as unreachable) for the log.
 */
suspend fun pick(
    nodes: List<Node>, k: Int, timeoutSec: Double, prefix: String, start: Int = 1,
    probe: suspend (Node) -> Double? = { tcpMs(it.ob, timeoutSec) },
    validator: ((Node) -> Boolean)? = null,
    extraUnreachable: Int = 0,
    note: (reachable: Int, extra: Int) -> Unit = { _, _ -> },
): LinkedHashMap<String, Node> {
    val ms = coroutineScope { nodes.map { n -> async { probe(n) } }.awaitAll() }
    val scored = nodes.zip(ms).filter { it.second != null }.sortedBy { it.second }.map { it.first }
    val ordered = scored.ifEmpty { nodes }
    val tail = if (scored.isEmpty()) emptyList() else nodes.zip(ms).filter { it.second == null }.map { it.first }.take(extraUnreachable)
    var chosen = ordered.take(k) + tail
    if (validator != null) {
        val good = ordered.take(maxOf(k * 3, k)).filter(validator).take(k)
        val goodTail = tail.filter(validator)
        if (good.isNotEmpty() || goodTail.isNotEmpty()) chosen = good + goodTail
    }
    note(scored.size, tail.size)
    val out = LinkedHashMap<String, Node>()
    chosen.forEachIndexed { i, n -> out["$prefix${start + i}"] = n }
    return out
}
