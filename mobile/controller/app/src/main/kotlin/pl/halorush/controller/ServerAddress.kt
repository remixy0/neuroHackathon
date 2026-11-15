package pl.halorush.controller

import java.net.URI

/**
 * Server address as typed on the phone. The HALO → Arcade server (`python -m backend`) prints
 * `ws://<IP>:8000/ws/controller`; typing that on a phone keyboard is slow and error-prone, so the bare
 * computer IP is enough and the rest is filled in.
 */
object ServerAddress {
    const val DEFAULT_PORT = 8000
    const val DEFAULT_PATH = "/ws/controller"

    /**
     * "172.20.10.2" -> "ws://172.20.10.2:8000/ws/controller", "192.168.1.20:8766" keeps its port.
     * A full ws:// or wss:// address stays as typed (only a missing path gets [DEFAULT_PATH]).
     * Returns null for anything the controller cannot connect to.
     */
    fun normalize(input: String): String? {
        val raw = input.trim()
        if (raw.isEmpty() || raw.any { it.isWhitespace() }) return null
        val full = raw.contains("://")
        val uri = try { URI(if (full) raw else "ws://$raw") } catch (_: Exception) { return null }
        if (uri.scheme !in listOf("ws", "wss") || uri.host.isNullOrBlank() || uri.userInfo != null ||
            uri.rawFragment != null) return null
        if (uri.port != -1 && uri.port !in 1..65535) return null
        val port = if (uri.port == -1 && !full) DEFAULT_PORT else uri.port
        val path = uri.rawPath.takeUnless { it.isNullOrEmpty() || it == "/" } ?: DEFAULT_PATH
        val query = uri.rawQuery?.let { "?$it" }.orEmpty()
        return "${uri.scheme}://${uri.host}${if (port == -1) "" else ":$port"}$path$query"
    }

    /** host:port for status lines. */
    fun short(url: String): String = try {
        URI(url).let { if (it.port == -1) it.host else "${it.host}:${it.port}" } ?: url
    } catch (_: Exception) { url }
}
