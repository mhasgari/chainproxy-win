package app.chainproxy.chain

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL

/** Status (null = no answer) and the first bytes of the body, as chain.via_proxy returns them. */
data class HttpResult(val status: Int?, val body: String)

data class Geo(val ip: String, val country: String?, val org: String)

const val USER_AGENT = "Mozilla/5.0 (Linux; Android 14) chainproxy/1.0"

/**
 * Where the network is touched, so tests can replace it. [viaProxy] fetches [url] through the local mixed inbound;
 * `until` stops reading as soon as the regex matches (a big page is not downloaded further than needed).
 */
interface VerifyIo {
    suspend fun viaProxy(url: String, port: Int, timeoutSec: Int, limit: Int = 65536, until: Regex? = null): HttpResult
    suspend fun geoLookup(cfg: ChainConfig): Geo?
}

/** Body bytes are kept as Latin-1 text so byte-level regexes behave exactly as on the desktop. */
object RealVerifyIo : VerifyIo {
    override suspend fun viaProxy(url: String, port: Int, timeoutSec: Int, limit: Int, until: Regex?): HttpResult =
        withContext(Dispatchers.IO) {
            val proxy = Proxy(Proxy.Type.HTTP, InetSocketAddress("127.0.0.1", port))
            var target = url
            try {
                for (hop in 0..5) {                                    // redirects, also http -> https (urllib does that)
                    val c = URL(target).openConnection(proxy) as HttpURLConnection
                    c.connectTimeout = timeoutSec * 1000
                    c.readTimeout = timeoutSec * 1000
                    c.instanceFollowRedirects = false
                    c.setRequestProperty("User-Agent", USER_AGENT)
                    try {
                        val code = c.responseCode
                        if (code in 301..308 && code != 304 && code != 305 && code != 306) {
                            val loc = c.getHeaderField("Location") ?: return@withContext HttpResult(code, "")
                            target = URL(URL(target), loc).toString()
                            continue
                        }
                        if (code >= 400) return@withContext HttpResult(code, "")
                        val out = ByteArrayOutputStream()
                        c.inputStream.use { input ->
                            val buf = ByteArray(16384)
                            while (out.size() < limit) {
                                val n = input.read(buf)
                                if (n < 0) break
                                out.write(buf, 0, n)
                                if (until != null && until.containsMatchIn(String(out.toByteArray(), Charsets.ISO_8859_1))) break
                            }
                        }
                        val bytes = out.toByteArray()
                        val keep = if (until == null) minOf(bytes.size, limit) else bytes.size
                        return@withContext HttpResult(code, String(bytes, 0, keep, Charsets.ISO_8859_1))
                    } finally {
                        c.disconnect()
                    }
                }
                HttpResult(null, "")
            } catch (e: Exception) {
                HttpResult(null, "")
            }
        }

    /** Exit IP/country through the active route. Providers are asked in parallel; the first valid answer wins. */
    override suspend fun geoLookup(cfg: ChainConfig): Geo? {
        val urls = (listOf(cfg.geoUrl) + cfg.geoFallbackUrls).filter { it.isNotEmpty() }
        if (urls.isEmpty()) return null
        return coroutineScope {
            val pending = urls.map { u ->
                async {
                    val r = viaProxy(u, cfg.mixedPort, minOf(cfg.verifyTimeout, 8))
                    if (r.status == 200) parseGeo(r.body) else null
                }
            }.toMutableList()
            var found: Geo? = null
            while (pending.isNotEmpty() && found == null) {
                val (done, value) = select<Pair<kotlinx.coroutines.Deferred<Geo?>, Geo?>> {
                    pending.forEach { d -> d.onAwait { d to it } }
                }
                pending.remove(done)
                found = value
            }
            pending.forEach { it.cancel() }
            found
        }
    }
}

/** Country Google itself assigns to the exit IP (WIZ_global_data holds it as "XX","ZZ"); null when absent. */
val GOOGLE_COUNTRY = Regex("""%\.@\.\\"([A-Z]{2})\\",\\"ZZ\\"""")

fun googleCountry(body: String?): String? = GOOGLE_COUNTRY.find(body.orEmpty())?.groupValues?.get(1)

private val geoJson = Json { ignoreUnknownKeys = true }

/** (ip, country code or null, org) from ipinfo.io / api.country.is / ipwho.is ... JSON; null when unusable. */
fun parseGeo(body: String): Geo? = try {
    val j = geoJson.parseToJsonElement(body).jsonObject
    fun text(k: String) = j[k]?.takeIf { it is kotlinx.serialization.json.JsonPrimitive }?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotEmpty() }
    val ip = text("ip") ?: text("query")
    val cc = (text("country_code") ?: text("countryCode") ?: text("country"))?.takeIf { it.length == 2 }?.uppercase()
    val org = text("org") ?: (j["connection"] as? JsonObject)?.get("org")?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotEmpty() }
        ?: text("isp") ?: ""
    if (ip == null) null else Geo(ip, cc, org)
} catch (e: Exception) {
    null
}

/** Exit-country check + strict sites in parallel. Returns (ok, info) with the same texts as chain.verify. */
suspend fun verify(cfg: ChainConfig, io: VerifyIo = RealVerifyIo): Pair<Boolean, String> = coroutineScope {
    val strict = cfg.strictUrls
    val geoD = if (cfg.geoUrl.isNotEmpty()) async { io.geoLookup(cfg) } else null
    val sitesD = strict.map { u ->
        u to async {
            if ("gemini.google" in u) io.viaProxy(u, cfg.mixedPort, cfg.verifyTimeout, 300000, GOOGLE_COUNTRY)
            else io.viaProxy(u, cfg.mixedPort, cfg.verifyTimeout)
        }
    }
    val geo = geoD?.await()
    val sites = sitesD.map { (u, d) -> Triple(u, d.await().status, d.await().body) }
    val blocked = cfg.blockedCountries.map { it.uppercase() }
    var info = "exit IP unknown"
    if (geo != null) {
        info = "${geo.ip} ${geo.country ?: "??"} ${geo.org}".trim()
        if (geo.country != null && geo.country in blocked) return@coroutineScope false to "exit in blocked country ($info)"
    }
    for ((url, st, body) in sites) {
        if (st == null || st >= 400) return@coroutineScope false to "$url -> ${if (st == null) "no answer" else st.toString()} ($info)"
        val seen = if ("gemini.google" in url) googleCountry(body) else null
        if (seen != null && seen in blocked) return@coroutineScope false to
            "$url -> Google places this exit in $seen (location not supported) ($info)"
    }
    true to info
}
