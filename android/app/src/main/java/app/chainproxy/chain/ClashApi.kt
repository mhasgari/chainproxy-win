package app.chainproxy.chain

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.net.URLEncoder

/** The sing-box Clash API (loopback): per-outbound delay tests and the "route" selector. */
class ClashApi(private val port: Int) : CoreApi {
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    private suspend fun call(method: String, path: String, body: String? = null, timeoutMs: Int = 15000): String =
        withContext(Dispatchers.IO) {
            val c = URL("http://127.0.0.1:$port$path").openConnection(Proxy.NO_PROXY) as HttpURLConnection
            try {
                c.requestMethod = method
                c.connectTimeout = timeoutMs
                c.readTimeout = timeoutMs
                if (body != null) {
                    c.doOutput = true
                    c.setRequestProperty("Content-Type", "application/json")
                    c.outputStream.use { it.write(body.toByteArray()) }
                }
                if (c.responseCode >= 400) throw java.io.IOException("HTTP ${c.responseCode}")
                c.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
            } finally {
                c.disconnect()
            }
        }

    suspend fun version(): String = call("GET", "/version", timeoutMs = 2000)

    override suspend fun delay(tag: String, url: String, timeoutMs: Int): Double? = try {
        val text = call("GET", "/proxies/${enc(tag)}/delay?url=${enc(url)}&timeout=$timeoutMs", timeoutMs = timeoutMs + 4000)
        Json.parseToJsonElement(text).jsonObject["delay"]?.jsonPrimitive?.contentOrNull?.toDoubleOrNull()
    } catch (e: Exception) {
        null
    }

    override suspend fun select(tag: String) {
        call("PUT", "/proxies/route", """{"name":${Json.encodeToString(kotlinx.serialization.serializer<String>(), tag)}}""")
    }
}
