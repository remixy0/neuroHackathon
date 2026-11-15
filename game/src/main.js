import './style.css'
import { View } from './scene.js'
import { DURATION, createTrack, createPlayer, command, advance, parseInput } from './engine.js'
const $ = id => document.getElementById(id)
let views
try {
    views = [new View($('canvas0'), 0x41b6d9, 723), new View($('canvas1'), 0xed7f9d, 723)]
} catch (error) {
    $('overlay-title').textContent = 'WebGL unavailable'
    $('overlay-text').textContent = 'Enable hardware acceleration or open the game in a browser that supports WebGL 2.'
    $('start').disabled = true
    throw error
}
let players,
    track,
    state = 'ready',
    elapsed = 0,
    countdown = 3,
    previous = performance.now(),
    animationTime = 0
let socket = null,
    reconnectTimer = null,
    wanted = false,
    retry = 0,
    seenIds = new Set(),
    feedbackTimers = []
function init() {
    players = [createPlayer(), createPlayer()]
    track = createTrack(crypto.getRandomValues(new Uint32Array(1))[0])
    views.forEach(v => v.reset(track))
    elapsed = 0
    countdown = 3
    for (let i = 0; i < 2; i++) {
        $('out' + i).hidden = true
        $('feedback' + i).textContent = ''
    }
    updateHud()
}
function feedback(i, text) {
    $('feedback' + i).textContent = text
    clearTimeout(feedbackTimers[i])
    feedbackTimers[i] = setTimeout(() => ($('feedback' + i).textContent = ''), 650)
}
function input(i, direction) {
    if (state !== 'running') return
    command(players[i], direction)
    $('input' + i).textContent = '● ' + { left: 'LEFT', right: 'RIGHT', up: 'JUMP', down: 'SLIDE' }[direction]
}
function updateHud() {
    players.forEach((p, i) => {
        $('score' + i).textContent = String(p.score).padStart(4, '0')
        $('coins' + i).textContent = '◈ ' + p.coins
        $('lives' + i).textContent = '♥ '.repeat(p.lives) + '♡ '.repeat(3 - p.lives)
    })
    const remaining = Math.max(0, Math.ceil(DURATION - elapsed))
    $('clock').textContent = String(Math.floor(remaining / 60)).padStart(2, '0') + ':' + String(remaining % 60).padStart(2, '0')
}
function begin() {
    init()
    state = 'countdown'
    $('overlay').hidden = true
    $('pause').disabled = false
    $('pause').textContent = 'Pause P'
    $('phase').textContent = 'GET READY'
}
function end() {
    state = 'finished'
    $('pause').disabled = true
    const a = players[0].score,
        b = players[1].score
    $('overlay-title').textContent = a === b ? 'It’s a tie!' : a > b ? 'Blue Comet wins!' : 'Pink Phantom wins!'
    $('overlay-text').textContent = `Blue Comet: ${a} pts · Pink Phantom: ${b} pts. Each meter earns 10 points; each coin earns 25.`
    $('instructions').hidden = true
    $('start').textContent = 'Rematch ↗'
    $('overlay').hidden = false
    $('phase').textContent = 'ROUND OVER'
}
function pause() {
    if (state === 'running' || state === 'countdown') {
        state = state === 'running' ? 'paused' : 'countdown-paused'
        $('phase').textContent = 'PAUSED'
        $('pause').textContent = 'Resume P'
    } else if (state === 'paused' || state === 'countdown-paused') {
        state = state === 'paused' ? 'running' : 'countdown'
        $('phase').textContent = 'RACE IN PROGRESS'
        $('pause').textContent = 'Pause P'
    }
}
$('start').onclick = begin
$('restart').onclick = begin
$('pause').onclick = pause
$('settings').onclick = () => {
    if (state === 'running' || state === 'countdown') pause()
    $('config').showModal()
}
const keys = { a: [0, 'left'], d: [0, 'right'], w: [0, 'up'], s: [0, 'down'], ArrowLeft: [1, 'left'], ArrowRight: [1, 'right'], ArrowUp: [1, 'up'], ArrowDown: [1, 'down'] }
window.addEventListener('keydown', e => {
    if ($('config').open || e.target instanceof HTMLInputElement) return
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
    if (keys[key]) {
        e.preventDefault()
        if (!e.repeat) input(...keys[key])
    }
    if (key === 'p' && !e.repeat) pause()
    if (e.code === 'Space' && !e.repeat && state === 'ready') {
        e.preventDefault()
        begin()
    }
})
document.addEventListener('visibilitychange', () => {
    if (document.hidden && (state === 'running' || state === 'countdown')) pause()
})
function connection(text, ok = false) {
    $('connection').textContent = text
    $('ws-status').textContent = text
    $('connection-dot').style.background = ok ? '#b5fc76' : '#8293a0'
}
function disconnect() {
    wanted = false
    clearTimeout(reconnectTimer)
    if (socket) {
        socket.onclose = null
        socket.close()
        socket = null
    }
    connection('KEYBOARD MODE')
}
function connect() {
    const url = $('ws-url').value.trim()
    let parsed
    try {
        parsed = new URL(url)
        if (!['ws:', 'wss:'].includes(parsed.protocol)) throw Error()
    } catch {
        connection('Invalid WebSocket URL')
        return
    }
    if (location.protocol === 'https:' && parsed.protocol === 'ws:') {
        connection('HTTPS pages require a wss:// connection')
        return
    }
    disconnect()
    wanted = true
    retry = 0
    seenIds.clear()
    try {
        localStorage.setItem('halo-ws', url)
    } catch {}
    openSocket(url)
}
function openSocket(url) {
    if (!wanted) return
    connection('CONNECTING…')
    let current
    try {
        current = new WebSocket(url)
    } catch {
        connection('Unable to open WebSocket connection')
        return
    }
    socket = current
    current.onopen = () => {
        retry = 0
        connection('HALO · CONNECTED', true)
    }
    current.onmessage = e => {
        const event = parseInput(e.data)
        if (!event) return
        if (event.id !== undefined) {
            const key = JSON.stringify([event.player, event.id])
            if (seenIds.has(key)) return
            seenIds.add(key)
            if (seenIds.size > 1000) seenIds.delete(seenIds.values().next().value)
        }
        input(event.player, event.direction)
    }
    current.onerror = () => connection('CONNECTION ERROR')
    current.onclose = () => {
        if (!wanted || socket !== current) return
        if (state === 'running' || state === 'countdown') pause()
        connection('DISCONNECTED · RECONNECTING…')
        reconnectTimer = setTimeout(() => openSocket(url), Math.min(1000 * 2 ** retry++, 10000))
    }
}
$('connect').onclick = connect
$('disconnect').onclick = disconnect
try {
    $('ws-url').value = localStorage.getItem('halo-ws') || 'ws://localhost:8765'
} catch {}
init()
function frame(now) {
    const dt = Math.min((now - previous) / 1000, 0.05)
    previous = now
    if (state === 'countdown') {
        countdown -= dt
        for (let i = 0; i < 2; i++) $('feedback' + i).textContent = Math.max(1, Math.ceil(countdown))
        if (countdown <= 0) {
            state = 'running'
            $('phase').textContent = 'RACE IN PROGRESS'
            for (let i = 0; i < 2; i++) feedback(i, 'GO!')
        }
    }
    if (state === 'running') {
        elapsed = Math.min(DURATION, elapsed + dt)
        animationTime += dt
        const speed = 11 + Math.min(elapsed * 0.075, 6)
        players.forEach((p, i) => {
            for (const event of advance(p, dt, speed, track)) {
                if (event === 'coin') feedback(i, '+25')
                if (event === 'hit') feedback(i, '−1 LIFE')
                if (event === 'out') $('out' + i).hidden = false
            }
        })
        updateHud()
        if (elapsed >= DURATION || players.every(p => !p.alive)) end()
    }
    views.forEach((v, i) => v.render(players[i], animationTime))
    requestAnimationFrame(frame)
}
requestAnimationFrame(frame)
