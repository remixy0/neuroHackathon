package pl.halorush.controller

import kotlinx.coroutines.*
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

/** Manual input has no local backlog: controls only send while a session is ready. */
class ManualController(private val status: (ConnectionUpdate) -> Unit) {
    private val http = BackendHttp.client(pingSeconds = 5)
    @Volatile private var active: BackendSocket? = null

    fun press(button: String): Boolean {
        val socket = active ?: return false
        return try { socket.sendManual(button); true }
        catch (e: IOException) { active = null; socket.abort(e); false }
    }

    suspend fun run(url: String, token: String, player: Int) {
        var attempt = 0
        while (currentCoroutineContext().isActive) {
            val socket = BackendSocket(http, UUID.randomUUID().toString(), player, {}, mode = "manual")
            var graceful = false
            try {
                status(ConnectionUpdate(ConnectionPhase.SERVER, "Connecting the controller to the server…"))
                socket.open(url, token)
                status(ConnectionUpdate(ConnectionPhase.REGISTERING, "Confirming manual mode…"))
                socket.handshake(Protocol.manualHello(socket.sessionId, player))
                active = socket
                status(ConnectionUpdate(ConnectionPhase.STREAMING, "Controller ready"))
                coroutineScope {
                    launch { socket.awaitFailure() }
                    val started = System.nanoTime()
                    while (isActive) {
                        delay(250)
                        socket.checkHealth()
                        if (System.nanoTime() - started > TimeUnit.SECONDS.toNanos(5)) attempt = 0
                    }
                }
            } catch (e: ProtocolException) { throw e
            } catch (e: TimeoutCancellationException) {
                currentCoroutineContext().ensureActive()
            } catch (e: CancellationException) { graceful = true; throw e
            } catch (_: IOException) { /* reconnect with a fresh session, without replaying presses */
            } finally { active = null; socket.close(graceful) }
            val seconds = minOf(1L shl minOf(attempt++, 4), 10L)
            status(ConnectionUpdate(ConnectionPhase.RETRYING, "Reconnecting in $seconds s. Buttons are paused."))
            delay(seconds * 1000)
        }
    }

    fun release() { active = null; http.dispatcher.executorService.shutdown(); http.connectionPool.evictAll() }
}
