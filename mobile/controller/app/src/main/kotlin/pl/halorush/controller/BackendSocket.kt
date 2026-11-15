package pl.halorush.controller

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.*
import okhttp3.*
import okio.ByteString
import java.io.IOException
import java.util.ArrayDeque
import java.util.concurrent.TimeUnit

class ProtocolException(message: String) : IOException(message)

/**
 * Tolerance for Wi-Fi stalls. Measured on the iPhone hotspot (15.11.2026): the phone's data stops for 0.5-2.7 s
 * and then arrives in one burst. With the old 2 s / 64 KiB limits every such stall ended the session (new
 * session = warm-up and calibration again). The server closes after 6 s without samples (backend EEG_IDLE_S)
 * and drops gestures from the late burst itself (host_time_ns), so waiting longer here is safe.
 */
internal const val ACK_TIMEOUT_S = 5L
internal const val MAX_QUEUE_BYTES = 256L * 1024 // ~8 s of samples at 50 packets/s

/** One socket = one fresh stream session. Never replay samples on reconnect. */
class BackendSocket(
    private val client: OkHttpClient,
    val sessionId: String,
    private val player: Int,
    private val onInput: (String) -> Unit,
    private val clockNs: () -> Long = System::nanoTime,
    private val mode: String = "eeg",
) : WebSocketListener() {
    private val opened = CompletableDeferred<Unit>()
    private val ready = CompletableDeferred<Unit>()
    private val failed = CompletableDeferred<Throwable>()
    private var socket: WebSocket? = null
    private var helloSent = false
    private var nextSeq = 0L
    private var lastAck = -1L
    private val pending = ArrayDeque<Pair<Long, Long>>()

    suspend fun open(url: String, token: String) {
        require(url.startsWith("ws://") || url.startsWith("wss://")) { "The address must start with ws:// or wss://" }
        val request = Request.Builder().url(url).apply {
            if (token.isNotBlank()) header("Authorization", "Bearer $token")
        }.build()
        socket = client.newWebSocket(request, this)
        withTimeout(10_000) { opened.await() }
    }

    suspend fun handshake(hello: String) {
        synchronized(this) {
            helloSent = true
            if (socket?.send(hello) != true) throw IOException("Could not send hello")
        }
        withTimeout(5_000) { ready.await() }
    }

    @Synchronized
    fun send(frame: SignalFrame, skipped: Long, missed: Long) {
        check(mode == "eeg")
        sendTracked { seq -> Protocol.samples(sessionId, seq, frame, skipped, missed) }
    }

    @Synchronized
    fun sendManual(button: String) {
        check(mode == "manual")
        require(button in Protocol.MANUAL_BUTTONS)
        sendTracked { seq -> Protocol.manual(sessionId, seq, player, button) }
    }

    private fun sendTracked(encode: (Long) -> String) {
        if (!ready.isCompleted || failed.isCompleted) throw IOException("Backend is not ready")
        val ws = socket ?: throw IOException("No WebSocket")
        checkHealth()
        if (ws.queueSize() > MAX_QUEUE_BYTES) throw IOException("Backend odbiera zbyt wolno")
        val seq = nextSeq++
        pending.addLast(seq to clockNs())
        if (!ws.send(encode(seq))) {
            throw IOException("Sending was interrupted")
        }
    }

    @Synchronized
    fun checkHealth() {
        val oldest = pending.peekFirst()
        if (oldest != null && clockNs() - oldest.second > TimeUnit.SECONDS.toNanos(ACK_TIMEOUT_S)) {
            throw IOException("No data acknowledgements from the server for $ACK_TIMEOUT_S s")
        }
    }

    suspend fun awaitFailure(): Nothing = throw failed.await()

    @Synchronized
    fun close(graceful: Boolean) {
        if (graceful && ready.isCompleted && !failed.isCompleted) {
            socket?.send(Protocol.stop(sessionId))
            socket?.close(1000, "Controller stopped")
        } else socket?.cancel()
        socket = null
    }

    override fun onOpen(webSocket: WebSocket, response: Response) { opened.complete(Unit) }

    @Synchronized
    override fun onMessage(webSocket: WebSocket, text: String) {
        try {
            if (text.length > 16_384) throw ProtocolException("Backend message too large")
            val msg = Json.parseToJsonElement(text).jsonObject
            if (msg["version"]?.jsonPrimitive?.intOrNull != Protocol.VERSION ||
                msg["session_id"]?.jsonPrimitive?.content != sessionId) {
                throw ProtocolException("Incompatible version or session id")
            }
            when (msg["type"]?.jsonPrimitive?.content) {
                "ready" -> {
                    if (!helloSent || ready.isCompleted || msg["player"]?.jsonPrimitive?.intOrNull != player)
                        throw ProtocolException("Invalid ready acknowledgement")
                    if ((msg["mode"]?.jsonPrimitive?.content ?: "eeg") != mode)
                        throw ProtocolException("The server did not confirm the selected controller mode")
                    ready.complete(Unit)
                }
                "ack" -> {
                    val seq = msg["seq"]?.jsonPrimitive?.longOrNull
                        ?: throw ProtocolException("Missing seq in ack")
                    if (!ready.isCompleted || seq < -1 || seq >= nextSeq)
                        throw ProtocolException("ACK outside the range of sent samples")
                    if (seq > lastAck) {
                        lastAck = seq
                        while (pending.peekFirst()?.first?.let { it <= seq } == true) pending.removeFirst()
                    }
                }
                "input" -> {
                    val direction = msg["direction"]?.jsonPrimitive?.content
                    if (!ready.isCompleted || msg["player"]?.jsonPrimitive?.intOrNull != player ||
                        direction !in listOf("left", "right", "up", "down"))
                        throw ProtocolException("Invalid input command")
                    onInput(direction!!)
                }
                "error" -> throw ProtocolException(msg["message"]?.jsonPrimitive?.content ?: "Backend rejected the session")
                else -> throw ProtocolException("Unknown backend message type")
            }
        } catch (e: Exception) {
            fail(if (e is ProtocolException) e else ProtocolException("Invalid backend JSON"))
            webSocket.cancel()
        }
    }

    override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
        fail(ProtocolException("Kontrakt v1 wymaga tekstowego JSON")); webSocket.cancel()
    }
    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
        fail(if (response?.code in listOf(401, 403, 404)) ProtocolException("Backend HTTP ${response?.code}: check the address and token") else t)
    }
    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
        webSocket.close(code, reason)
        fail(if (code in listOf(1002, 1003, 1008)) ProtocolException("Backend rejected the session: $reason") else IOException("Backend closed the connection ($code)"))
    }
    private fun fail(error: Throwable) {
        failed.complete(error); opened.completeExceptionally(error); ready.completeExceptionally(error)
    }

    fun abort(error: Throwable) { fail(error); socket?.cancel() }
}
