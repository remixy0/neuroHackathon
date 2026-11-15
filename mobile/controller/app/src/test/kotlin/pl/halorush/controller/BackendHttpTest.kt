package pl.halorush.controller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetSocketAddress
import java.net.ServerSocket

class BackendHttpTest {
    @Test fun `sockets to the server send small frames at once (no Nagle)`() {
        val factory = NoDelaySocketFactory()
        ServerSocket(0).use { server ->
            // OkHttp creates an unconnected socket and connects it itself
            factory.createSocket().use { s ->
                assertTrue(s.tcpNoDelay)
                s.connect(InetSocketAddress("127.0.0.1", server.localPort), 2000)
                assertTrue(s.tcpNoDelay)
            }
            factory.createSocket("127.0.0.1", server.localPort).use { assertTrue(it.tcpNoDelay) }
        }
    }

    @Test fun `both controllers use the tuned client`() {
        val client = BackendHttp.client(pingSeconds = 10)
        assertTrue(client.socketFactory is NoDelaySocketFactory)
        assertEquals(10_000, client.pingIntervalMillis)
        assertEquals(0, client.readTimeoutMillis)
    }
}
