package app.chainproxy.chain

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Checks the Kotlin port against chain.py's own output (src/test/resources/golden.json, see dev/android/gen_golden.py). */
class ChainGoldenTest {
    private val golden: JsonObject = Json.parseToJsonElement(
        javaClass.classLoader!!.getResourceAsStream("golden.json")!!.readBytes().toString(Charsets.UTF_8)).jsonObject

    private fun cases(name: String) = golden.getValue(name).jsonArray.map { it.jsonObject }
    private fun JsonElement.strings() = jsonArray.map { it.jsonPrimitive.content }
    private fun JsonObject.str(k: String) = getValue(k).jsonPrimitive.content
    private fun nodes(o: JsonObject) = LinkedHashMap<String, Node>().also { m ->
        o.forEach { (tag, v) -> m[tag] = Node(v.jsonObject.str("name"), v.jsonObject.getValue("ob").jsonObject) }
    }

    @Test fun normalizeUrl() {
        for (c in cases("normalize")) assertEquals(c.str("in"), c.str("out"), normalizeUrl(c.str("in")))
    }

    @Test fun parseNode() {
        for (c in cases("parse")) {
            val link = c.str("link")
            val got = parseNode(link)
            val want = c.getValue("expect")
            if (want is JsonNull) {
                assertNull("must be rejected: $link", got)
            } else {
                assertTrue("must parse: $link", got != null)
                assertEquals("name of $link", want.jsonObject.str("name"), got!!.name)
                assertEquals("outbound of $link", want.jsonObject.getValue("ob"), got.ob)
            }
        }
    }

    @Test fun subscriptions() {
        for (c in cases("subscription")) {
            val got = decodeSubscription(c.str("body"))
            val want = c.getValue("expect").jsonArray
            assertEquals(c.str("label"), want.size, got.size)
            want.forEachIndexed { i, w ->
                assertEquals(c.str("label"), w.jsonObject.str("name"), got[i].name)
                assertEquals(c.str("label"), w.jsonObject.getValue("ob"), got[i].ob)
            }
        }
    }

    @Test fun singBoxConfig() {
        for (c in cases("config")) {
            val k = c.getValue("cfg").jsonObject
            val cfg = ChainConfig(
                mixedPort = k.getValue("mixed_port").jsonPrimitive.int, apiPort = k.getValue("api_port").jsonPrimitive.int,
                privateDirect = k.getValue("private_direct").jsonPrimitive.boolean,
                directSuffixes = k.getValue("direct_suffixes").strings(), logLevel = k.str("log_level"))
            val got = buildConfig(cfg, nodes(c.getValue("A").jsonObject), nodes(c.getValue("B").jsonObject),
                c.getValue("modern").jsonPrimitive.boolean)
            assertEquals(c.str("label"), c.getValue("expect"), got)
        }
    }

    @Test fun geoAnswers() {
        for (c in cases("geo")) {
            val got = parseGeo(c.str("body"))
            val want = c.getValue("expect")
            if (want is JsonNull) assertNull(c.str("body"), got)
            else {
                assertEquals(want.jsonObject.str("ip"), got!!.ip)
                assertEquals(want.jsonObject.getValue("cc").jsonPrimitive.contentOrNull, got.country)
                assertEquals(want.jsonObject.str("org"), got.org)
            }
        }
    }

    @Test fun googleCountryMarker() {
        for (c in cases("google")) assertEquals(c.str("body"), c.getValue("expect").jsonPrimitive.contentOrNull, googleCountry(c.str("body")))
    }

    private class NoCore(val delays: Map<String, Double?>) : CoreApi {
        override suspend fun delay(tag: String, url: String, timeoutMs: Int) = delays[tag]
        override suspend fun select(tag: String) {}
    }

    @Test fun routeRanking() = runBlocking {
        for (c in cases("rank")) {
            val a = c.getValue("A").strings()
            val b = c.getValue("B").strings()
            val delays = c.getValue("delays").jsonObject.mapValues { it.value.jsonPrimitive.contentOrNull?.toDouble() }
            val tiers = c.getValue("tiers").jsonObject.mapValues { it.value.jsonPrimitive.int }
            val dummy = Node("n", JsonObject(emptyMap()))
            val rm = RouteManager(ChainConfig(rankBySpeed = c.getValue("rank_by_speed").jsonPrimitive.boolean), NoCore(delays), { true to "" })
            rm.setNodes(a.associateWith { dummy }, b.associateWith { dummy }, tiers)
            rm.buildRank()
            assertEquals(c.str("label"), c.getValue("expect").strings(), rm.rank)
        }
    }

    private class FakeIo(val geo: Geo?, val sites: Map<String, HttpResult>) : VerifyIo {
        override suspend fun viaProxy(url: String, port: Int, timeoutSec: Int, limit: Int, until: Regex?) = sites.getValue(url)
        override suspend fun geoLookup(cfg: ChainConfig) = geo
    }

    @Test fun verification() = runBlocking {
        for (c in cases("verify")) {
            val g = c.getValue("geo")
            val geo = if (g is JsonNull) null else g.jsonArray.let { Geo(it[0].jsonPrimitive.content, it[1].jsonPrimitive.contentOrNull, it[2].jsonPrimitive.content) }
            val sites = c.getValue("sites").jsonObject.mapValues { (_, v) ->
                HttpResult(v.jsonObject.getValue("status").jsonPrimitive.contentOrNull?.toInt(), v.jsonObject.str("body"))
            }
            val cfg = ChainConfig(blockedCountries = c.getValue("blocked_countries").strings(), strictUrls = c.getValue("strict_urls").strings())
            val (ok, info) = verify(cfg, FakeIo(geo, sites))
            val want = c.getValue("expect").jsonArray
            assertEquals(c.str("label"), want[0].jsonPrimitive.boolean, ok)
            assertEquals(c.str("label"), want[1].jsonPrimitive.content, info)
        }
    }
}
