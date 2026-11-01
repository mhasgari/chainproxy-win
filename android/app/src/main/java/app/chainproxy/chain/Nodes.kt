package app.chainproxy.chain

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.util.Base64

/*
 * Subscription links -> sing-box outbounds. A port of chain.py (parse_node and friends); the golden vectors in
 * src/test/resources/golden.json are produced by chain.py itself (dev/android/gen_golden.py), so the two
 * implementations are kept equal by tests, not by reading.
 */

/** A parsed proxy: display name + sing-box outbound (without tag). */
data class Node(val name: String, val ob: JsonObject)

fun normalizeUrl(u: String): String {
    val s = u.trim()
    if (s.isEmpty()) return ""
    return if (Regex("^[a-z][a-z0-9+.-]*://", RegexOption.IGNORE_CASE).containsMatchIn(s)) s else "https://$s"
}

/** Lenient base64 (url-safe or not, padding optional), like chain.b64d. Throws on undecodable input. */
fun b64d(input: String): String {
    var s = input.trim().replace('-', '+').replace('_', '/')
    s += "=".repeat((4 - s.length % 4) % 4)
    val clean = s.filter { it.isLetterOrDigit() && it.code < 128 || it == '+' || it == '/' || it == '=' }
    return String(Base64.getDecoder().decode(clean), Charsets.UTF_8)
}

/** urllib.parse.unquote: percent-decoding as UTF-8, undecodable bytes become U+FFFD. */
fun unquote(s: String): String {
    if ('%' !in s) return s
    val out = java.io.ByteArrayOutputStream()
    var i = 0
    while (i < s.length) {
        val c = s[i]
        if (c == '%' && i + 2 < s.length && s.substring(i + 1, i + 3).all { it in "0123456789abcdefABCDEF" }) {
            out.write(s.substring(i + 1, i + 3).toInt(16))
            i += 3
        } else {
            out.write(c.toString().toByteArray(Charsets.UTF_8))
            i++
        }
    }
    return String(out.toByteArray(), Charsets.UTF_8)
}

/** The parts of urllib.parse.urlparse that the link formats use. */
class Url(val scheme: String, val username: String?, val password: String?, val hostname: String?, val port: Int?,
          val query: String, val fragment: String) {
    companion object {
        /** Throws IllegalArgumentException for a bad port (urlparse(...).port raises ValueError). */
        fun parse(link: String): Url {
            val schemeEnd = link.indexOf("://")
            require(schemeEnd > 0) { "no scheme" }
            val scheme = link.substring(0, schemeEnd).lowercase()
            var rest = link.substring(schemeEnd + 3)
            var fragment = ""
            rest.indexOf('#').let { if (it >= 0) { fragment = rest.substring(it + 1); rest = rest.substring(0, it) } }
            var query = ""
            rest.indexOf('?').let { if (it >= 0) { query = rest.substring(it + 1); rest = rest.substring(0, it) } }
            val netloc = rest.substringBefore('/')
            val at = netloc.lastIndexOf('@')
            val userinfo = if (at >= 0) netloc.substring(0, at) else null
            val hostinfo = if (at >= 0) netloc.substring(at + 1) else netloc
            var username: String? = null
            var password: String? = null
            if (userinfo != null) {
                if (':' in userinfo) {
                    username = userinfo.substringBefore(':')
                    password = userinfo.substringAfter(':')
                } else username = userinfo
            }
            val host: String?
            val portText: String?
            if (hostinfo.startsWith("[")) {
                val close = hostinfo.indexOf(']')
                require(close > 0) { "bad IPv6 host" }
                host = hostinfo.substring(1, close)
                val after = hostinfo.substring(close + 1)
                portText = if (after.startsWith(":")) after.substring(1) else null
            } else {
                host = hostinfo.substringBefore(':').ifEmpty { null }
                portText = if (':' in hostinfo) hostinfo.substringAfter(':') else null
            }
            var port: Int? = null
            if (!portText.isNullOrEmpty()) {
                require(portText.all { it in '0'..'9' }) { "bad port" }
                port = portText.toInt()
                require(port in 0..65535) { "port out of range" }
            }
            return Url(scheme, username, password, host?.lowercase(), port, query, fragment)
        }
    }
}

/** First value of every non-blank parameter (urllib.parse.parse_qs, keep_blank_values=False). */
fun firstParams(query: String): Map<String, String> {
    val out = LinkedHashMap<String, String>()
    for (pair in query.split('&')) {
        if (pair.isEmpty() || '=' !in pair) continue
        val k = unquote(pair.substringBefore('=').replace('+', ' '))
        val v = unquote(pair.substringAfter('=').replace('+', ' '))
        if (v.isEmpty()) continue
        out.putIfAbsent(k, v)
    }
    return out
}

private fun Map<String, String>.s(key: String) = this[key].orEmpty()

fun tlsBlock(p: Map<String, String>, host: String?, force: Boolean = false): JsonObject? {
    val sec = p.s("security")
    if (sec != "tls" && sec != "reality" && !force) return null
    return buildJsonObject {
        put("enabled", true)
        val sni = p.s("sni").ifEmpty { p.s("peer") }.ifEmpty { host.orEmpty() }
        if (sni.isNotEmpty()) put("server_name", sni)
        if (p["allowInsecure"] in setOf("1", "true") || p["insecure"] in setOf("1", "true")) put("insecure", true)
        if (p.s("alpn").isNotEmpty()) putJsonArray("alpn") { p.s("alpn").split(",").filter { it.isNotEmpty() }.forEach { add(JsonPrimitive(it)) } }
        val fp = p.s("fp")
        if (fp.isNotEmpty() || sec == "reality") putJsonObject("utls") {
            put("enabled", true)
            put("fingerprint", fp.ifEmpty { "chrome" })
        }
        if (sec == "reality") putJsonObject("reality") {
            put("enabled", true)
            put("public_key", p.s("pbk"))
            put("short_id", p.s("sid"))
        }
    }
}

fun transportBlock(p: Map<String, String>): JsonObject? {
    val typ = p["type"]?.takeIf { it.isNotEmpty() } ?: "tcp"
    val host = p.s("host")
    var path = p.s("path").ifEmpty { "/" }
    when (typ) {
        "ws" -> return buildJsonObject {
            put("type", "ws")
            val ed = Regex("[?&]ed=(\\d+)").find(path)
            if (ed != null) {
                put("max_early_data", ed.groupValues[1].toInt())
                put("early_data_header_name", "Sec-WebSocket-Protocol")
                path = path.replace(Regex("[?&]ed=\\d+"), "").ifEmpty { "/" }
            }
            put("path", path)
            if (host.isNotEmpty()) putJsonObject("headers") { put("Host", host) }
        }
        "grpc" -> return buildJsonObject { put("type", "grpc"); put("service_name", p.s("serviceName")) }
        "httpupgrade" -> return buildJsonObject {
            put("type", "httpupgrade"); put("path", path)
            if (host.isNotEmpty()) put("host", host)
        }
        "h2", "http" -> return buildJsonObject {
            put("type", "http"); put("path", path)
            if (host.isNotEmpty()) putJsonArray("host") { host.split(",").filter { it.isNotEmpty() }.forEach { add(JsonPrimitive(it)) } }
        }
    }
    return null
}

private val json = Json { ignoreUnknownKeys = true }

private fun JsonObject.str(key: String, default: String = ""): String {
    val v = this[key] ?: return default
    return if (v is JsonNull) default else v.jsonPrimitive.contentOrNull ?: default
}

private fun JsonObject.intOf(key: String, default: Int = 0): Int {
    val v = this[key]?.takeIf { it !is JsonNull }?.jsonPrimitive?.contentOrNull ?: return default
    return if (v.isEmpty()) default else v.toInt()
}

private fun JsonObject.withPut(extra: JsonObject?, key: String): JsonObject =
    if (extra == null) this else JsonObject(this + (key to extra))

/** One share link -> (name, outbound); null when the format is unknown or the link is damaged. */
fun parseNode(rawLink: String): Node? {
    val link = rawLink.trim()
    try {
        when (link.substringBefore("://", "").lowercase()) {
            "vmess" -> {
                val j = json.parseToJsonElement(b64d(link.substring(8))).jsonObject
                val add = j["add"]!!.jsonPrimitive.content
                val p = mapOf("security" to j.str("tls"), "sni" to j.str("sni"), "alpn" to j.str("alpn"), "fp" to j.str("fp"),
                    "type" to j.str("net", "tcp"), "host" to j.str("host"), "path" to j.str("path", "/"),
                    "serviceName" to j.str("path"))
                var ob = buildJsonObject {
                    put("type", "vmess"); put("server", add)
                    put("server_port", j["port"]!!.jsonPrimitive.content.toInt())
                    put("uuid", j["id"]!!.jsonPrimitive.content)
                    put("alter_id", j.intOf("aid"))
                    put("security", j.str("scy").ifEmpty { "auto" })
                }
                ob = ob.withPut(tlsBlock(p, j.str("host").ifEmpty { add }), "tls").withPut(transportBlock(p), "transport")
                return Node(if (j.containsKey("ps")) j.str("ps") else add, ob)
            }
            "vless", "trojan" -> {
                val scheme = link.substringBefore("://").lowercase()
                val u = Url.parse(link)
                val p = firstParams(u.query)
                val name = unquote(u.fragment).ifEmpty { u.hostname.orEmpty() }
                val user = unquote(u.username ?: return null)
                val portValue = u.port?.let { JsonPrimitive(it) } ?: JsonNull
                var ob: JsonObject
                val tls: JsonObject?
                if (scheme == "vless") {
                    ob = buildJsonObject {
                        put("type", "vless"); put("server", u.hostname.orEmpty()); put("server_port", portValue)
                        put("uuid", user); put("packet_encoding", "xudp")
                        if (p.s("flow").isNotEmpty()) put("flow", p.s("flow"))
                    }
                    tls = tlsBlock(p, u.hostname)
                } else {
                    ob = buildJsonObject {
                        put("type", "trojan"); put("server", u.hostname.orEmpty()); put("server_port", portValue)
                        put("password", user)
                    }
                    tls = tlsBlock(p, u.hostname, force = true)
                }
                ob = ob.withPut(tls, "tls").withPut(transportBlock(p), "transport")
                return Node(name, ob)
            }
            "ss" -> {
                val body = link.substring(5).substringBefore('#')
                val frag = if ('#' in link.substring(5)) link.substring(5).substringAfter('#') else ""
                val name = unquote(frag)
                val main = body.substringBefore('?')
                val query = if ('?' in body) body.substringAfter('?') else ""
                if ("plugin=" in query) return null
                val userinfo: String
                val hostport: String
                if ('@' in main) {
                    val at = main.lastIndexOf('@')
                    var ui = unquote(main.substring(0, at))
                    hostport = main.substring(at + 1)
                    if (':' !in ui) ui = b64d(ui)
                    userinfo = ui
                } else {
                    val dec = b64d(main)
                    val at = dec.lastIndexOf('@')
                    userinfo = dec.substring(0, at)
                    hostport = dec.substring(at + 1)
                }
                val method = userinfo.substringBefore(':')
                require(':' in userinfo)
                val pw = userinfo.substringAfter(':')
                val colon = hostport.lastIndexOf(':')
                val host = hostport.substring(0, colon).trim('[', ']')
                val port = hostport.substring(colon + 1).trim('/').toInt()
                return Node(name.ifEmpty { host }, buildJsonObject {
                    put("type", "shadowsocks"); put("server", host); put("server_port", port)
                    put("method", method); put("password", pw)
                })
            }
            "hysteria2", "hy2" -> {
                val u = Url.parse(link)
                val p = firstParams(u.query)
                var pw = unquote(u.username.orEmpty())
                if (!u.password.isNullOrEmpty()) pw += ":" + unquote(u.password)
                val host = u.hostname.orEmpty()
                val ob = buildJsonObject {
                    put("type", "hysteria2"); put("server", host); put("server_port", u.port ?: 443)
                    put("password", pw)
                    putJsonObject("tls") {
                        put("enabled", true)
                        put("server_name", p.s("sni").ifEmpty { host })
                        if (p["insecure"] in setOf("1", "true")) put("insecure", true)
                    }
                    if (p["obfs"] == "salamander") putJsonObject("obfs") {
                        put("type", "salamander"); put("password", p.s("obfs-password"))
                    }
                }
                return Node(unquote(u.fragment).ifEmpty { host }, ob)
            }
        }
    } catch (e: Exception) {
        return null
    }
    return null
}

/** Identity of a node for de-duplication: (type, server, port, uuid-or-password). */
fun nodeKey(ob: JsonObject): List<String> = listOf(
    ob.str("type"), ob.str("server"), ob["server_port"]?.toString().orEmpty(),
    ob.str("uuid").ifEmpty { ob.str("password") })

/** Subscription body (plain links or base64 of them) -> unique nodes. */
fun decodeSubscription(body: String): List<Node> {
    var text = body.trim()
    if (text.isEmpty()) return emptyList()
    if (!Regex("^[a-z0-9]+://", setOf(RegexOption.MULTILINE, RegexOption.IGNORE_CASE)).containsMatchIn(text)) {
        text = try { b64d(text) } catch (e: Exception) { return emptyList() }
    }
    val seen = HashSet<List<String>>()
    val nodes = ArrayList<Node>()
    for (line in text.lines()) {
        val n = parseNode(line) ?: continue
        if (seen.add(nodeKey(n.ob))) nodes.add(n)
    }
    return nodes
}

/** Profile lists: one link per line, '#' lines are comments. Returns (nodes, number of lines not recognized). */
fun decodeProfiles(text: String): Pair<List<Node>, Int> {
    val seen = HashSet<List<String>>()
    val nodes = ArrayList<Node>()
    var bad = 0
    for (raw in text.lines()) {
        val line = raw.trim()
        if (line.isEmpty() || line.startsWith("#")) continue
        val n = parseNode(line)
        if (n == null) bad++ else if (seen.add(nodeKey(n.ob))) nodes.add(n)
    }
    return nodes to bad
}
