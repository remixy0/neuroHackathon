package pl.halorush.controller

import com.neurotec.brainaccess.core.DeviceSession
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collect
import okhttp3.OkHttpClient
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

data class StreamStats(val samples: Long, val discarded: Long, val missed: Long,
                       val battery: Float, val contacts: List<Pair<String, Boolean>>, val rate: Int)

class Controller(
    private val status: (String) -> Unit,
    private val stats: (StreamStats) -> Unit,
    private val input: (String) -> Unit,
) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS)
        .pingInterval(10, TimeUnit.SECONDS).build()

    suspend fun run(session: DeviceSession, url: String, token: String, player: Int) {
        // Explicitly restore EEG, 250 Hz, all default channels; never inherit impedance mode.
        session.configure(session.model.defaultConfig()).getOrThrow()
        var attempt = 0
        while (currentCoroutineContext().isActive) {
            val backend = BackendSocket(http, UUID.randomUUID().toString(), player, input)
            var graceful = false
            try {
                status("Łączenie z backendem…")
                backend.open(url, token)
                coroutineScope {
                    var initialized = false
                    var layout: SignalFrame? = null
                    var sent = 0L
                    var discarded = 0L
                    val lastReceived = AtomicLong(System.nanoTime())
                    var lastUi = 0L
                    val failure = launch { backend.awaitFailure() }
                    val watchdog = launch {
                        while (isActive) {
                            delay(250)
                            backend.checkHealth()
                            check(System.nanoTime() - lastReceived.get() < TimeUnit.SECONDS.toNanos(8)) {
                                "HALO nie wysyła danych. Sprawdź Bluetooth i połącz opaskę ponownie."
                            }
                        }
                    }
                    try {
                        session.stream().collect { chunk ->
                            val now = System.nanoTime()
                            lastReceived.set(now)
                            val frame = SignalFrame(
                                chunk.channels, chunk.srate, chunk.sampleCount,
                                chunk.samples, chunk.accel, chunk.gyro, chunk.firstSampleIndex,
                                chunk.wireLastSampleIndex, chunk.hostTimeNs, chunk.isDummy,
                                chunk.contact, chunk.batteryPct,
                            )
                            if (!initialized) {
                                status("Rejestracja sesji gracza $player…")
                                backend.handshake(Protocol.hello(backend.sessionId, player, session.id.toString(),
                                    session.name, session.hardware.toString(), frame))
                                layout = frame
                                initialized = true
                                status("Transmisja aktywna · gracz $player")
                            }
                            val initial = checkNotNull(layout)
                            check(frame.channels == initial.channels && frame.sampleRate == initial.sampleRate &&
                                (frame.accel != null) == (initial.accel != null) && (frame.gyro != null) == (initial.gyro != null)) {
                                "Konfiguracja HALO zmieniła się w trakcie sesji"
                            }
                            // SDK stamps arrival before decoding. Drop any backlog after handshake or a stall.
                            if (System.nanoTime() - frame.hostTimeNs > TimeUnit.MILLISECONDS.toNanos(500)) {
                                discarded += frame.count
                            } else {
                                backend.send(frame, discarded, session.missedSamples.value)
                                sent += frame.count
                            }
                            if (sent >= frame.sampleRate * 5L) attempt = 0
                            if (now - lastUi > TimeUnit.MILLISECONDS.toNanos(200)) {
                                lastUi = now
                                stats(StreamStats(sent, discarded, session.missedSamples.value, frame.battery,
                                    frame.channels.zip(frame.contact.toList()), frame.sampleRate))
                            }
                        }
                        error("HALO zakończyło transmisję. Połącz opaskę ponownie.")
                    } finally {
                        failure.cancel(); watchdog.cancel()
                    }
                }
            } catch (e: ProtocolException) {
                throw e
            } catch (e: TimeoutCancellationException) {
                currentCoroutineContext().ensureActive()
                status("Backend nie odpowiedział w terminie")
            } catch (e: CancellationException) {
                graceful = true
                throw e
            } catch (e: IOException) {
                status(e.message ?: "Utracono połączenie z backendem")
            } finally {
                backend.close(graceful)
            }
            val seconds = minOf(1L shl minOf(attempt++, 4), 10L)
            status("Ponowne połączenie za ${seconds} s · bez zaległych próbek")
            delay(seconds * 1000)
        }
    }

    fun release() {
        http.dispatcher.executorService.shutdown()
        http.connectionPool.evictAll()
    }
}
