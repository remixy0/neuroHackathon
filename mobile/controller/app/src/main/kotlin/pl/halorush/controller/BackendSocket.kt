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
        require(url.startsWith("ws://") || url.startsWith("wss://")) { "Adres musi zaczynać się od ws:// lub wss://" }
        val request = Request.Builder().url(url).apply {
            if (token.isNotBlank()) header("Authorization", "Bearer $token")
        }.build()
        socket = client.newWebSocket(request, this)
        withTimeout(10_000) { opened.await() }
    }

    suspend fun handshake(hello: String) {
        synchronized(this) {
            helloSent = true
            if (socket?.send(hello) != true) throw IOException("Nie można wysłać hello")
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
        if (!ready.isCompleted || failed.isCompleted) throw IOException("Backend nie jest gotowy")
        val ws = socket ?: throw IOException("Brak WebSocket")
        checkHealth()
        if (ws.queueSize() > 64 * 1024) throw IOException("Backend odbiera zbyt wolno")
        val seq = nextSeq++
        pending.addLast(seq to clockNs())
        if (!ws.send(encode(seq))) {
            throw IOException("Przerwano wysyłanie")
        }
    }

    @Synchronized
    fun checkHealth() {
        val oldest = pending.peekFirst()
        if (oldest != null && clockNs() - oldest.second > TimeUnit.SECONDS.toNanos(2)) {
            throw IOException("Brak potwierdzeń danych od serwera przez 2 s")
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
            if (text.length > 16_384) throw ProtocolException("Za duża wiadomość backendu")
            val msg = Json.parseToJsonElement(text).jsonObject
            if (msg["version"]?.jsonPrimitive?.intOrNull != Protocol.VERSION ||
                msg["session_id"]?.jsonPrimitive?.content != sessionId) {
                throw ProtocolException("Niezgodna wersja lub identyfikator sesji")
            }
            when (msg["type"]?.jsonPrimitive?.content) {
                "ready" -> {
                    if (!helloSent || ready.isCompleted || msg["player"]?.jsonPrimitive?.intOrNull != player)
                        throw ProtocolException("Nieprawidłowe potwierdzenie ready")
                    if ((msg["mode"]?.jsonPrimitive?.content ?: "eeg") != mode)
                        throw ProtocolException("Serwer nie potwierdził wybranego trybu kontrolera")
                    ready.complete(Unit)
                }
                "ack" -> {
                    val seq = msg["seq"]?.jsonPrimitive?.longOrNull
                        ?: throw ProtocolException("Brak seq w ack")
                    if (!ready.isCompleted || seq < -1 || seq >= nextSeq)
                        throw ProtocolException("ACK poza zakresem wysłanych próbek")
                    if (seq > lastAck) {
                        lastAck = seq
                        while (pending.peekFirst()?.first?.let { it <= seq } == true) pending.removeFirst()
                    }
                }
                "input" -> {
                    val direction = msg["direction"]?.jsonPrimitive?.content
                    if (!ready.isCompleted || msg["player"]?.jsonPrimitive?.intOrNull != player ||
                        direction !in listOf("left", "right", "up", "down"))
                        throw ProtocolException("Nieprawidłowa komenda input")
                    onInput(direction!!)
                }
                "error" -> throw ProtocolException(msg["message"]?.jsonPrimitive?.content ?: "Backend odrzucił sesję")
                else -> throw ProtocolException("Nieznany typ wiadomości backendu")
            }
        } catch (e: Exception) {
            fail(if (e is ProtocolException) e else ProtocolException("Nieprawidłowy JSON backendu"))
            webSocket.cancel()
        }
    }

    override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
        fail(ProtocolException("Kontrakt v1 wymaga tekstowego JSON")); webSocket.cancel()
    }
    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
        fail(if (response?.code in listOf(401, 403, 404)) ProtocolException("Backend HTTP ${response?.code}: sprawdź adres i token") else t)
    }
    override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
        webSocket.close(code, reason)
        fail(if (code in listOf(1002, 1003, 1008)) ProtocolException("Backend odrzucił sesję: $reason") else IOException("Backend zamknął połączenie ($code)"))
    }
    private fun fail(error: Throwable) {
        failed.complete(error); opened.completeExceptionally(error); ready.completeExceptionally(error)
    }

    fun abort(error: Throwable) { fail(error); socket?.cancel() }
}
