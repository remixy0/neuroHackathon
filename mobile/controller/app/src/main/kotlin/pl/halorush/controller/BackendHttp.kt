package pl.halorush.controller

import okhttp3.OkHttpClient
import java.net.InetAddress
import java.net.Socket
import java.util.concurrent.TimeUnit
import javax.net.SocketFactory

/**
 * OkHttp leaves Nagle's algorithm on (it never calls `setTcpNoDelay`). The phone sends a small frame every
 * 20 ms; with Nagle each frame waits until the previous one is acknowledged, so on a slow Wi-Fi link they
 * leave in clumps and late by up to one round trip. Recordings from 15.11.2026 showed exactly that on one
 * phone: 2-4 packets arriving in the same millisecond, median delay 0.15-0.25 s instead of 0.02 s.
 * The server side already sends without delay (asyncio sets TCP_NODELAY on every connection).
 */
internal class NoDelaySocketFactory(private val base: SocketFactory = getDefault()) : SocketFactory() {
    private fun Socket.tuned(): Socket = apply { tcpNoDelay = true }
    override fun createSocket(): Socket = base.createSocket().tuned()
    override fun createSocket(host: String, port: Int): Socket = base.createSocket(host, port).tuned()
    override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket =
        base.createSocket(host, port, localHost, localPort).tuned()
    override fun createSocket(host: InetAddress, port: Int): Socket = base.createSocket(host, port).tuned()
    override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket =
        base.createSocket(address, port, localAddress, localPort).tuned()
}

/** One client setup for both controllers (HALO and the on-screen pad). */
internal object BackendHttp {
    fun client(pingSeconds: Long): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS)
        .pingInterval(pingSeconds, TimeUnit.SECONDS)
        .socketFactory(NoDelaySocketFactory())
        .build()
}
