package app.chainproxy.chain

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject

const val LANTERN_NAME = "Lantern (auto)"

/** The first-hop node that stands for the Lantern engine's local SOCKS port. */
fun lanternNode(port: Int) = Node(LANTERN_NAME, buildJsonObject {
    put("type", "socks"); put("server", "127.0.0.1"); put("server_port", port); put("version", "5")
})

private fun JsonObject.tagged(tag: String, detour: String? = null) = JsonObject(
    this + ("tag" to JsonPrimitive(tag)) + (if (detour != null) mapOf("detour" to JsonPrimitive(detour)) else emptyMap()))

/**
 * Port of chain.build_config: every A->B chain (B dials through A), every B and A alone, a selector "route" that
 * the app switches through the Clash API. [modern] adds the explicit domain resolver sing-box >= 1.12 wants.
 */
fun buildConfig(cfg: ChainConfig, a: Map<String, Node>, b: Map<String, Node>, modern: Boolean = true): JsonObject {
    val outs = ArrayList<JsonElement>()
    outs.add(buildJsonObject { put("type", "direct"); put("tag", "direct") })
    for ((tag, n) in a + b) outs.add(n.ob.tagged(tag))
    val chains = ArrayList<String>()
    for (ta in a.keys) for (tb in b.keys) {
        val tag = "$ta-$tb"
        outs.add(b.getValue(tb).ob.tagged(tag, detour = ta))      // client -> A -> B -> net
        chains.add(tag)
    }
    val allTags = chains + b.keys + a.keys
    outs.add(buildJsonObject {
        put("type", "selector"); put("tag", "route")
        putJsonArray("outbounds") { allTags.forEach { add(JsonPrimitive(it)) } }
        put("default", allTags.first())
    })
    val rules = ArrayList<JsonElement>()
    if (cfg.privateDirect) rules.add(buildJsonObject { put("ip_is_private", true); put("outbound", "direct") })
    if (cfg.directSuffixes.isNotEmpty()) rules.add(0, buildJsonObject {
        putJsonArray("domain_suffix") { cfg.directSuffixes.forEach { add(JsonPrimitive(it)) } }
        put("outbound", "direct")
    })
    return buildJsonObject {
        putJsonObject("log") { put("level", cfg.logLevel); put("timestamp", true) }
        putJsonArray("inbounds") {
            add(buildJsonObject {
                put("type", "mixed"); put("tag", "in"); put("listen", "127.0.0.1"); put("listen_port", cfg.mixedPort)
            })
        }
        put("outbounds", JsonArray(outs))
        putJsonObject("route") {
            put("rules", JsonArray(rules)); put("final", "route")
            if (modern) put("default_domain_resolver", "local")
        }
        putJsonObject("experimental") {
            putJsonObject("clash_api") { put("external_controller", "127.0.0.1:${cfg.apiPort}") }
        }
        if (modern) putJsonObject("dns") {
            putJsonArray("servers") { add(buildJsonObject { put("type", "local"); put("tag", "local") }) }
        }
    }
}

/**
 * The same configuration plus what a phone needs: a TUN inbound that captures every app (VpnService), traffic
 * sniffing (so domain rules work for IP connections), DNS hijack, and name resolution THROUGH the chain
 * (the system resolver would leak the lookups). Sites that go direct (".ir") are resolved locally.
 */
fun androidConfig(cfg: ChainConfig, a: Map<String, Node>, b: Map<String, Node>): JsonObject {
    val base = buildConfig(cfg, a, b, modern = true)
    val tun = buildJsonObject {
        put("type", "tun"); put("tag", "tun-in")
        putJsonArray("address") { add(JsonPrimitive("172.19.0.1/30")); add(JsonPrimitive("fdfe:dcba:9876::1/126")) }
        put("mtu", 1400); put("auto_route", true); put("stack", "gvisor")
        // per-app split tunnelling (sing-box Android options)
        if (cfg.splitApps.isNotEmpty() && cfg.splitMode == "include") putJsonArray("include_package") { cfg.splitApps.forEach { add(JsonPrimitive(it)) } }
        if (cfg.splitApps.isNotEmpty() && cfg.splitMode == "exclude") putJsonArray("exclude_package") { cfg.splitApps.forEach { add(JsonPrimitive(it)) } }
    }
    val route = base.getValue("route") as JsonObject
    val rules = buildJsonArray {
        add(buildJsonObject { put("action", "sniff") })
        add(buildJsonObject { put("protocol", "dns"); put("action", "hijack-dns") })
        (route.getValue("rules") as JsonArray).forEach { add(it) }
    }
    val dnsRules = buildJsonArray {
        if (cfg.directSuffixes.isNotEmpty()) add(buildJsonObject {
            putJsonArray("domain_suffix") { cfg.directSuffixes.forEach { add(JsonPrimitive(it)) } }
            put("server", "local")
        })
    }
    val dns = buildJsonObject {
        putJsonArray("servers") {
            add(buildJsonObject { put("type", "local"); put("tag", "local") })
            add(buildJsonObject {
                put("type", "https"); put("tag", "remote"); put("server", "1.1.1.1"); put("detour", "route")
                put("domain_resolver", "local")
            })
        }
        put("rules", dnsRules)
        put("final", "remote")
    }
    return JsonObject(base + mapOf(
        "inbounds" to JsonArray(listOf(tun) + (base.getValue("inbounds") as JsonArray)),
        "route" to JsonObject(route + mapOf("rules" to rules, "auto_detect_interface" to JsonPrimitive(true))),
        "dns" to dns,
    ))
}
