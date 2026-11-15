package pl.halorush.controller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerAddressTest {
    @Test fun `bare IP is enough`() {
        assertEquals("ws://172.20.10.2:8000/ws/controller", ServerAddress.normalize("172.20.10.2"))
        assertEquals("ws://192.168.1.20:8000/ws/controller", ServerAddress.normalize("  192.168.1.20 "))
        assertEquals("ws://localhost:8000/ws/controller", ServerAddress.normalize("localhost"))
    }

    @Test fun `own port and path are kept`() {
        assertEquals("ws://192.168.1.20:8766/ws/controller", ServerAddress.normalize("192.168.1.20:8766"))
        assertEquals("ws://192.168.1.20:8000/ws/controller", ServerAddress.normalize("ws://192.168.1.20:8000/ws/controller"))
        assertEquals("ws://192.168.1.20:8000/ws/controller", ServerAddress.normalize("ws://192.168.1.20:8000"))
        assertEquals("wss://halo.example.com/ws/controller", ServerAddress.normalize("wss://halo.example.com/ws/controller"))
        assertEquals("ws://10.0.0.5:9000/custom?x=1", ServerAddress.normalize("ws://10.0.0.5:9000/custom?x=1"))
    }

    @Test fun `unusable addresses are refused`() {
        for (bad in listOf("", "   ", "http://192.168.1.20:8000", "192.168 .1.20", "ws://user@host/ws",
                "ws://host:99999/ws", "ws://host/ws#frag", "ws:///ws/controller")) {
            assertNull(bad, ServerAddress.normalize(bad))
        }
    }

    @Test fun `short form for screens`() {
        assertEquals("172.20.10.2:8000", ServerAddress.short("ws://172.20.10.2:8000/ws/controller"))
        assertEquals("halo.example.com", ServerAddress.short("wss://halo.example.com/ws/controller"))
    }
}
