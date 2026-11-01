package app.chainproxy.chain

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Test

class PickTest {
    private val nodes = (1..6).map { Node("n$it", buildJsonObject { put("type", "socks"); put("server", "h$it"); put("server_port", it) }) }
    private val reachable = mapOf("n2" to 30.0, "n5" to 10.0)
    private val probe: suspend (Node) -> Double? = { reachable[it.name] }

    @Test
    fun unreachableNodesAreDroppedByDefault() = runBlocking {
        val r = pick(nodes, 5, 1.0, "B", probe = probe)
        assertEquals(listOf("n5", "n2"), r.values.map { it.name })
    }

    @Test
    fun extraUnreachableNodesFollowTheReachableOnes() = runBlocking {
        var seen = -1 to -1
        val r = pick(nodes, 5, 1.0, "B", probe = probe, extraUnreachable = 3, note = { a, b -> seen = a to b })
        assertEquals(listOf("n5", "n2", "n1", "n3", "n4"), r.values.map { it.name })
        assertEquals(listOf("B1", "B2", "B3", "B4", "B5"), r.keys.toList())
        assertEquals(2 to 3, seen)
    }

    @Test
    fun whenNothingIsReachableAllNodesAreKeptOnce() = runBlocking {
        val r = pick(nodes, 4, 1.0, "B", probe = { null }, extraUnreachable = 3)
        assertEquals(listOf("n1", "n2", "n3", "n4"), r.values.map { it.name })
    }
}
