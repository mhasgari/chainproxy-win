package app.chainproxy.chain

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test
import java.net.ServerSocket
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class VerifyIoTest {
    /**
     * Every verification request must open a NEW connection to the local proxy. A kept-alive tunnel keeps using the route
     * that was active when it was opened, so after a route switch the check would judge the previous route again
     * (all routes then show the same exit IP and are accepted or rejected together).
     */
    @Test
    fun everyRequestUsesAFreshProxyConnection() {
        val accepted = AtomicInteger()
        ServerSocket(0, 10, java.net.InetAddress.getByName("127.0.0.1")).use { server ->
            thread(isDaemon = true) {
                while (true) {
                    val s = try { server.accept() } catch (e: Exception) { return@thread }
                    accepted.incrementAndGet()
                    thread(isDaemon = true) {
                        // a keep-alive HTTP/1.1 proxy: answers every request on the same socket until the client leaves
                        try {
                            val input = s.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                            while (true) {
                                var line = input.readLine() ?: break
                                var close = false
                                while (line.isNotEmpty()) {
                                    if (line.lowercase().replace(" ", "") == "connection:close") close = true
                                    line = input.readLine() ?: break
                                }
                                val head = "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n" + (if (close) "Connection: close\r\n" else "") + "\r\nok"
                                s.getOutputStream().write(head.toByteArray(Charsets.ISO_8859_1)); s.getOutputStream().flush()
                                if (close) break
                            }
                        } catch (e: Exception) { /* client closed */ } finally { s.close() }
                    }
                }
            }
            runBlocking {
                repeat(3) { assertEquals(200, RealVerifyIo.viaProxy("http://verify.test/", server.localPort, 5).status) }
            }
        }
        assertEquals(3, accepted.get())
    }
}
