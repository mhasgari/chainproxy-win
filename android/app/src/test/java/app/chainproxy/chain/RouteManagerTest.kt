package app.chainproxy.chain

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlinx.serialization.json.put

class RouteManagerTest {
    private class Core(val delays: Map<String, Double?>) : CoreApi {
        val selected = ArrayList<String>()
        override suspend fun delay(tag: String, url: String, timeoutMs: Int) = delays[tag]
        override suspend fun select(tag: String) { selected.add(tag) }
    }

    private val dummy = Node("node", JsonObject(emptyMap()))
    private val delays = mapOf("A1-B1" to 100.0, "A1-B2" to 200.0, "B1" to 50.0, "B2" to 60.0, "A1" to 40.0)

    private fun manager(core: Core, bad: Set<String>): RouteManager {
        val rm = RouteManager(ChainConfig(), core, { if (core.selected.last() in bad) false to "blocked" else true to "1.2.3.4 DE" })
        rm.setNodes(mapOf("A1" to dummy), mapOf("B1" to dummy, "B2" to dummy), mapOf("A1" to 2, "B1" to 1, "B2" to 1))
        return rm
    }

    @Test fun nextSkipsRejectedRoutesAndRemembersWhy() = runBlocking {
        val rm = manager(Core(delays), setOf("A1-B1"))
        rm.buildRank()
        assertEquals(listOf("A1-B1", "A1-B2", "B1", "B2", "A1"), rm.rank)
        rm.go(1)
        assertEquals(1, rm.idx)
        assertEquals("blocked", rm.rows.value.first { it.tag == "A1-B1" }.rejected)
        rm.go(1)
        assertEquals(2, rm.idx)
        rm.go(-1)
        assertEquals(1, rm.idx)
    }

    @Test fun goToFallsBackToThePreviousRoute() = runBlocking {
        val core = Core(delays)
        val rm = manager(core, setOf("B1"))
        rm.buildRank()
        rm.go(1)
        assertEquals(0, rm.idx)
        val msg = rm.goTo(2)
        assertTrue(msg, msg.startsWith("route rejected"))
        assertEquals(0, rm.idx)
        assertEquals("A1-B1", core.selected.last())
    }

    @Test fun allRejected() = runBlocking {
        val core = Core(delays)
        val rm = manager(core, delays.keys)
        rm.buildRank()
        assertTrue(rm.go(1).startsWith("no route passed"))
        assertEquals(-1, rm.idx)
    }

    @Test fun rescanRanksAgain() = runBlocking {
        val rm = manager(Core(delays), emptySet())
        val msg = rm.rescan()
        assertTrue(msg, msg.startsWith("[1/5]"))
    }

    @Test fun pickKeepsFastestAndFallsBackWhenNothingAnswers() = runBlocking {
        val nodes = (1..6).map { Node("n$it", JsonObject(emptyMap())) }
        val ms = mapOf("n1" to 300.0, "n2" to 100.0, "n3" to null, "n4" to 200.0, "n5" to null, "n6" to 400.0)
        val got = pick(nodes, 3, 1.0, "B", probe = { ms[it.name] })
        assertEquals(listOf("B1" to "n2", "B2" to "n4", "B3" to "n1"), got.map { it.key to it.value.name })
        val none = pick(nodes, 2, 1.0, "A", start = 101, probe = { null })
        assertEquals(listOf("A101" to "n1", "A102" to "n2"), none.map { it.key to it.value.name })
    }

    @Test fun configJsonRoundTripAndTolerance() {
        val cfg = ChainConfig(strictUrls = listOf("gemini.google.com"), mixedPort = 1234).normalized()
        assertEquals(listOf("https://gemini.google.com"), cfg.strictUrls)
        assertEquals(1234, ChainConfig.fromJson(cfg.toJson()).mixedPort)
        assertEquals(ChainConfig().normalized(), ChainConfig.fromJson("{ broken"))
    }
}

class AndroidConfigTest {
    private val a = mapOf("A1" to Node("a", kotlinx.serialization.json.buildJsonObject { put("type", kotlinx.serialization.json.JsonPrimitive("socks")) }))
    private val b = mapOf("B1" to Node("b", kotlinx.serialization.json.buildJsonObject { put("type", kotlinx.serialization.json.JsonPrimitive("socks")) }))

    private fun tun(cfg: ChainConfig) = (androidConfig(cfg, a, b)["inbounds"] as kotlinx.serialization.json.JsonArray)[0] as JsonObject

    @Test fun tunInboundAndSplitTunnelling() {
        assertEquals("tun", (tun(ChainConfig())["type"] as kotlinx.serialization.json.JsonPrimitive).content)
        assertTrue(tun(ChainConfig()).keys.none { it.endsWith("_package") })
        assertTrue("include_package" in tun(ChainConfig(splitMode = "include", splitApps = listOf("a.b"))))
        assertTrue("exclude_package" in tun(ChainConfig(splitMode = "exclude", splitApps = listOf("a.b"))))
        assertTrue(tun(ChainConfig(splitMode = "include")).keys.none { it.endsWith("_package") })     // nothing selected = everything
    }

    @Test fun dnsGoesThroughTheChainExceptDirectSuffixes() {
        val conf = androidConfig(ChainConfig(), a, b)
        val dns = conf["dns"] as JsonObject
        assertEquals("remote", (dns["final"] as kotlinx.serialization.json.JsonPrimitive).content)
        assertEquals(1, (dns["rules"] as kotlinx.serialization.json.JsonArray).size)
        val rules = (conf["route"] as JsonObject)["rules"] as kotlinx.serialization.json.JsonArray
        assertEquals("sniff", ((rules[0] as JsonObject)["action"] as kotlinx.serialization.json.JsonPrimitive).content)
    }
}
