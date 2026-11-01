package app.chainproxy.update

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class UpdateCheckerNetTest {
    private val releases = """[{"tag_name":"android-v9.9.9","assets":[{"name":"ChainProxy-9.9.9-x86_64.apk","browser_download_url":"http://x/a.apk"}]}]"""

    /** A one-shot HTTP server (also usable as an HTTP proxy: a plain-http proxy request is answered like a normal one). */
    private fun serve(hits: AtomicInteger): ServerSocket {
        val server = ServerSocket(0, 10, InetAddress.getByName("127.0.0.1"))
        thread(isDaemon = true) {
            while (true) {
                val s = try { server.accept() } catch (e: Exception) { return@thread }
                hits.incrementAndGet()
                thread(isDaemon = true) {
                    try {
                        val r = s.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                        while (r.readLine().orEmpty().isNotEmpty()) { /* skip the request head */ }
                        val body = releases.toByteArray()
                        s.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n").toByteArray() + body)
                        s.getOutputStream().flush()
                    } catch (e: Exception) { } finally { s.close() }
                }
            }
        }
        return server
    }

    private fun closedPort() = ServerSocket(0).use { it.localPort }

    @Test
    fun goesThroughTheLocalProxyWhenItIsRunning() {
        val viaProxy = AtomicInteger()
        serve(viaProxy).use { proxy ->
            // the api host does not exist: only the proxy can answer
            val r = runBlocking { UpdateChecker.check("", "0.0.1", api = "http://api.invalid/releases", proxyPort = proxy.localPort, abis = listOf("x86_64")) }
            assertNotNull(r.getOrThrow())
            assertEquals(1, viaProxy.get())
        }
    }

    @Test
    fun fallsBackToTheDirectConnectionWhenNothingListensOnTheProxyPort() {
        val direct = AtomicInteger()
        serve(direct).use { server ->
            val r = runBlocking {
                UpdateChecker.check("", "0.0.1", api = "http://127.0.0.1:${server.localPort}/releases", proxyPort = closedPort(), abis = listOf("x86_64"))
            }
            assertEquals("9.9.9", r.getOrThrow()?.version)
            assertEquals(1, direct.get())
        }
    }
}
