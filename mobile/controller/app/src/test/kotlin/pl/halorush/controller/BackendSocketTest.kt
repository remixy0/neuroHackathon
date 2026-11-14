package pl.halorush.controller

import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class BackendSocketTest {
    private fun message(type: String, extra: String = "", session: String = "test") =
        """{"type":"$type","version":1,"session_id":"$session"$extra}"""

    @Test fun `handshake samples cumulative ack command and stop roundtrip`() = runBlocking<Unit> {
        val server = MockWebServer()
        val http = OkHttpClient()
        val input = CompletableDeferred<String>()
        val stopped = CompletableDeferred<Unit>()
        val packet = CompletableDeferred<JsonObject>()
        var now = 0L
        val backend = BackendSocket(http, "test", 1, { input.complete(it) }, { now })
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onMessage(ws: WebSocket, text: String) {
                val data = Json.parseToJsonElement(text).jsonObject
                when (data["type"]?.jsonPrimitive?.content) {
                    "hello" -> ws.send(message("ready", ",\"player\":1"))
                    "samples" -> {
                        packet.complete(data)
                        ws.send(message("ack", ",\"seq\":0"))
                        ws.send(message("input", ",\"player\":1,\"direction\":\"left\""))
                    }
                    "stop" -> stopped.complete(Unit)
                }
            }
            override fun onClosing(ws: WebSocket, code: Int, reason: String) { ws.close(code, reason) }
        }))
        try {
            backend.open(server.url("/ws/controller").toString().replaceFirst("http", "ws"), "secret")
            backend.handshake(Protocol.hello("test", 1, "d", "HALO", "HALO_V3", fixture()))
            backend.send(fixture(), 0, 0)
            withTimeout(3000) {
                assertEquals("left", input.await())
                assertEquals(0L, packet.await().getValue("seq").jsonPrimitive.long)
            }
            now = 3_000_000_000L
            backend.checkHealth() // ack removed the pending packet
            backend.close(true)
            withTimeout(3000) { stopped.await() }
            assertEquals("Bearer secret", server.takeRequest().getHeader("Authorization"))
        } finally { backend.close(false); server.close(); http.dispatcher.executorService.shutdown(); http.connectionPool.evictAll() }
    }

    @Test fun `wrong session is terminal and no samples are allowed before ready`() = runBlocking<Unit> {
        val server = MockWebServer()
        val http = OkHttpClient()
        val backend = BackendSocket(http, "test", 1, {})
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onMessage(ws: WebSocket, text: String) { ws.send(message("ready", ",\"player\":1", "wrong")) }
        }))
        try {
            backend.open(server.url("/").toString().replaceFirst("http", "ws"), "")
            assertThrows(IOException::class.java) { backend.send(fixture(), 0, 0) }
            try {
                backend.handshake(Protocol.hello("test", 1, "d", "HALO", "HALO_V3", fixture()))
                fail("Expected protocol rejection")
            } catch (_: ProtocolException) { /* expected */ }
        } finally { backend.close(false); server.close(); http.dispatcher.executorService.shutdown(); http.connectionPool.evictAll() }
    }

    @Test fun `missing ack expires outstanding samples`() = runBlocking<Unit> {
        val server = MockWebServer()
        val http = OkHttpClient()
        var now = 0L
        val backend = BackendSocket(http, "test", 1, {}, { now })
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onMessage(ws: WebSocket, text: String) {
                if (Json.parseToJsonElement(text).jsonObject["type"]?.jsonPrimitive?.content == "hello")
                    ws.send(message("ready", ",\"player\":1"))
            }
        }))
        try {
            backend.open(server.url("/").toString().replaceFirst("http", "ws"), "")
            backend.handshake(Protocol.hello("test", 1, "d", "HALO", "HALO_V3", fixture()))
            backend.send(fixture(), 0, 0)
            now = 2_000_000_001L
            assertThrows(IOException::class.java) { backend.checkHealth() }
        } finally { backend.close(false); server.close(); http.dispatcher.executorService.shutdown(); http.connectionPool.evictAll() }
    }
}
