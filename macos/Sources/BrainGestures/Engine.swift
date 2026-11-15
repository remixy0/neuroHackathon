import Foundation
import SwiftUI

/// Wynik zapisu sesji treningowej w tym czepku (zdarzenie "session" z silnika).
struct SessionResult: Equatable {
    let ok: Bool
    let id: String
    let path: String
    let duration: Double
    let status: String
    let counts: [String: Int]
    let message: String
}

/// Zebrane dane osoby w jednym trybie (wszystkie sesje).
struct ModeStats: Equatable {
    var sessions = 0
    var minutes = 0.0
    var trials = 0
}

/// Analogowa pozycja z silnika: procenty -100...100 (x > 0 = w prawo, y > 0 = w gore) i stopnie.
struct HeadEye: Equatable {
    var headX = 0.0, headY = 0.0, yawDeg = 0.0, pitchDeg = 0.0
    var eyesX = 0.0, eyesCalibrated = false, eyesOk = true
}

/// Ekran "Kalibracja glowy": stan z silnika (tools/gestures/tilt.py TiltScreen, zdarzenie "tilt" ok. 10 razy na s).
struct TiltState: Equatable {
    /// Wychylenie glowy wzgledem srodka w strone kazdego kierunku [°] (ujemne = w przeciwna strone).
    var angles: [String: Double] = [:]
    /// Prog kazdego kierunku [°]: z zapisanej kalibracji albo domyslny.
    var thresholds: [String: Double] = [:]
    var step: String?
    var counts: [String: Int] = [:]
    /// Wynik zbieranej kalibracji: kierunek -> (najwieksze wychylenie, prog); nil = za maly ruch.
    var preview: [String: (angle: Double?, threshold: Double?)] = [:]
    var previewReady = false        // jest srodek (krok spokoju) - mozna zapisac
    var saved = false               // czepek ma zapisana kalibracje
    var ready = false               // detektor zna srodek glowy

    static func == (a: TiltState, b: TiltState) -> Bool {
        a.angles == b.angles && a.thresholds == b.thresholds && a.step == b.step && a.counts == b.counts
            && a.previewReady == b.previewReady && a.saved == b.saved && a.ready == b.ready
            && a.preview.keys == b.preview.keys
            && a.preview.allSatisfy { k, v in b.preview[k].map { $0.angle == v.angle && $0.threshold == v.threshold } ?? false }
    }
}

/// Ruch glowy wykryty na ekranie kalibracji (te same progi co w grze).
struct TiltHit: Identifiable {
    let id = UUID()
    let key: String
    let at: Date
}

struct Device: Identifiable, Equatable {
    var id: String { address + name }
    let name: String
    let address: String
}

struct Gesture: Identifiable {
    let id = UUID()
    let start: Double
    let end: Double
    let key: String
    let confidence: Double
    let familyConfidence: Double
}

struct Bar: Identifiable {
    var id: String { key }
    let key: String
    let value: Double
}

enum EngineState: String {
    case stopped, starting, idle, scanning, connecting, streaming, error
}

/// Jeden czepek: osobny proces silnika (tools/engine.py), osobna osoba, osobne rozpoznawanie.
final class Engine: ObservableObject, Identifiable {
    let slot: Int
    var id: Int { slot }

    @Published var state: EngineState = .stopped
    @Published var message = ""
    @Published var devices: [Device] = []
    @Published var demoFiles: [String] = []
    @Published var sourceName = ""
    @Published var isDemo = false
    @Published var battery: Int?
    @Published var contact: [String: Bool] = [:]
    @Published var lost = 0.0
    @Published var position: HeadEye?
    /// Zapisane proby emocji tej osoby: emocja -> liczba.
    @Published var emoCounts: [String: Int] = [:]
    @Published var lastEmoMessage = ""
    private var emoByPerson: [String: [String: Int]] = [:]
    @Published var person: String {
        didSet {
            UserDefaults.standard.set(person, forKey: "person\(slot)")
            applySessionStats()
            applyEmoCounts()
            sendPerson()
        }
    }

    @Published var time = 0.0
    @Published var label = "rest"
    @Published var confidence = 0.0
    @Published var family = "rest"
    @Published var familyConfidence = 0.0
    @Published var warmup = false
    @Published var families: [Bar] = []
    @Published var top: [Bar] = []
    @Published var gestures: [Gesture] = []
    @Published var traces: [String: [Double]] = [:]

    // sesje treningowe osoby w tym czepku
    @Published var sessionRecording = false
    @Published var lastSession: SessionResult?
    @Published var modeStats: [String: ModeStats] = [:]   // tryb -> zebrane dane tej osoby
    private var sessionsByPerson: [String: [String: [String: Double]]] = [:]
    @Published var modelState = "none"
    @Published var modelMessage = ""
    @Published var modelSamples = 0

    // ekran "Kalibracja glowy" (zapis: training/calibration/tilt_<czepek>.json, czyta go serwer HALO -> Arcade)
    @Published var tilt: TiltState?
    @Published var tiltHits: [TiltHit] = []
    @Published var tiltMessage = ""
    @Published var tiltSavedOK = false

    /// Wywolywane przy zmianach istotnych dla calej aplikacji (stan, sesje) - nie przy kazdej probce.
    var onChange: (() -> Void)?

    static let traceOrder = ["Fp1", "Fp2", "O1", "O2", "gx", "gy", "gz"]
    static let electrodes = ["Fp1", "Fp2", "O1", "O2"]
    private let maxPoints = 300  // 6 s przy 50 Hz

    private var process: Process?
    private var input: FileHandle?
    private var buffer = Data()
    private var stderrTail = ""
    private var pendingDemo: String?

    var isStreaming: Bool { state == .streaming }
    var isRunning: Bool { process != nil }
    var title: String { "Czepek \(slot)" }

    init(slot: Int) {
        self.slot = slot
        self.person = UserDefaults.standard.string(forKey: "person\(slot)") ?? "osoba\(slot)"
    }

    func start() {
        guard process == nil else { return }
        state = .starting
        message = "Uruchamiam silnik…"
        guard let (python, script) = Self.locateEngine() else {
            state = .error
            message = "Nie znaleziono silnika (tools/engine.py). Zbuduj aplikację skryptem macos/build.sh."
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = ["-u", script]
        p.currentDirectoryURL = URL(fileURLWithPath: script).deletingLastPathComponent()
        var env = ProcessInfo.processInfo.environment
        env["BRAINGESTURES_SLOT"] = String(slot)
        p.environment = env
        let inPipe = Pipe(), outPipe = Pipe(), errPipe = Pipe()
        p.standardInput = inPipe
        p.standardOutput = outPipe
        p.standardError = errPipe
        outPipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            guard !data.isEmpty else { return }
            DispatchQueue.main.async { self?.consume(data) }
        }
        errPipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let data = h.availableData
            guard !data.isEmpty, let s = String(data: data, encoding: .utf8) else { return }
            DispatchQueue.main.async {
                guard let self else { return }
                self.stderrTail = String((self.stderrTail + s).suffix(600))
            }
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self, self.process === proc else { return }
                self.process = nil
                self.state = .error
                let tail = self.stderrTail.split(separator: "\n").last.map(String.init) ?? ""
                self.message = "Silnik zakończył pracę (kod \(proc.terminationStatus)). \(tail)"
                self.sessionRecording = false
                self.onChange?()
            }
        }
        do {
            try p.run()
            process = p
            input = inPipe.fileHandleForWriting
        } catch {
            state = .error
            message = "Nie można uruchomić silnika: \(error.localizedDescription)"
        }
        let flag = slot == 1 ? "--demo" : "--demo\(slot)"
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: flag), i + 1 < args.count { pendingDemo = args[i + 1] }
        onChange?()
    }

    func stop() {
        guard let p = process else { return }
        process = nil
        send(["cmd": "quit"])
        DispatchQueue.global().asyncAfter(deadline: .now() + 1.5) { if p.isRunning { p.terminate() } }
        state = .stopped
        message = ""
        sessionRecording = false
        onChange?()
    }

    private static func locateEngine() -> (String, String)? {
        let fm = FileManager.default
        if let url = Bundle.main.url(forResource: "engine", withExtension: "json"),
           let data = try? Data(contentsOf: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String],
           let py = obj["python"], let sc = obj["script"], fm.fileExists(atPath: py), fm.fileExists(atPath: sc) {
            return (py, sc)
        }
        if let tools = ProcessInfo.processInfo.environment["BRAINGESTURES_TOOLS"] {
            let py = tools + "/.venv/bin/python", sc = tools + "/engine.py"
            if fm.fileExists(atPath: py), fm.fileExists(atPath: sc) { return (py, sc) }
        }
        return nil
    }

    // MARK: polecenia

    func send(_ obj: [String: Any]) {
        guard let input, var data = try? JSONSerialization.data(withJSONObject: obj) else { return }
        data.append(0x0A)
        try? input.write(contentsOf: data)
    }

    func scan() { devices = []; send(["cmd": "scan"]) }
    func connect(_ d: Device) { resetSession(); sourceName = d.name; send(["cmd": "connect", "name": d.name]) }
    func demo(_ path: String) {
        resetSession()
        sourceName = URL(fileURLWithPath: path).lastPathComponent
        send(["cmd": "demo", "path": path])
    }
    func disconnect() { send(["cmd": "disconnect"]) }

    // MARK: sesje treningowe (zapis: tools/session_recorder.py)

    func sessionStart(mode: String, protocolInfo: [String: Any], instructions: String, at date: Date) {
        lastSession = nil
        sessionRecording = true
        send(["cmd": "session_start", "mode": mode, "person": person.trimmingCharacters(in: .whitespaces),
              "unix_time": date.timeIntervalSince1970, "protocol": protocolInfo, "instructions": instructions])
    }

    /// Znacznik w danych sesji. Czas = chwila pokazania/odtworzenia bodzca (zegar komputera).
    func sessionEvent(_ event: String, label: String? = nil, trial: Int? = nil, x: Double? = nil, xTo: Double? = nil,
                      duration: Double? = nil, details: [String: Any]? = nil, at date: Date = Date()) {
        var c: [String: Any] = ["cmd": "session_event", "event": event, "unix_time": date.timeIntervalSince1970]
        if let label { c["label"] = label }
        if let trial { c["trial"] = trial }
        if let x { c["x"] = x }
        if let xTo { c["x_to"] = xTo }
        if let duration { c["duration_s"] = duration }
        if let details { c["details"] = details }
        send(c)
    }

    func sessionStop(status: String) {
        send(["cmd": "session_stop", "unix_time": Date().timeIntervalSince1970, "status": status])
    }

    // proby emocji: start (spokoj) -> faza "induction" -> "end" (koniec nagrania) -> stop z ocena
    func emoStart(_ emotion: String, source: String, round: Int, note: String) {
        send(["cmd": "emo_start", "person": person.trimmingCharacters(in: .whitespaces), "emotion": emotion,
              "source": source, "round": round, "note": note])
    }
    func emoPhase(_ phase: String) { send(["cmd": "emo_phase", "phase": phase]) }
    func emoStop(ratings: EmoRating?) {
        if let r = ratings {
            send(["cmd": "emo_stop", "save": true, "ratings": ["valence": r.valence, "arousal": r.arousal,
                                                               "intensity": r.intensity, "felt": r.felt]])
        } else {
            send(["cmd": "emo_stop", "save": false])
        }
    }
    private func applyEmoCounts() { emoCounts = emoByPerson[person.trimmingCharacters(in: .whitespaces)] ?? [:] }
    // MARK: kalibracja glowy (akcelerometr)

    /// Otwiera ekran (silnik zaczyna wysylac stan) i czysci zebrane kroki.
    func tiltStart() { tiltMessage = ""; tiltSavedOK = false; send(["cmd": "tilt_start"]) }
    /// Krok kalibracji: "neutral", "head_left"...; nil = nie zbieramy.
    func tiltStep(_ step: String?) { send(["cmd": "tilt_step", "step": step ?? NSNull()]) }
    func tiltSave() { send(["cmd": "tilt_save"]) }
    func tiltStop() { send(["cmd": "tilt_stop"]); tilt = nil; tiltHits = [] }

    /// Silnik kalibruje odczyt oczu na probach spojrzen tej osoby.
    func sendPerson() { send(["cmd": "person", "name": person.trimmingCharacters(in: .whitespaces)]) }
    func requestSessionsState() { send(["cmd": "sessions_state"]) }

    private func resetSession() {
        gestures = []; traces = [:]; families = []; top = []; battery = nil; contact = [:]
        confidence = 0; familyConfidence = 0; label = "rest"; family = "rest"; time = 0; lost = 0
        position = nil
        tilt = nil; tiltHits = []; tiltMessage = ""; tiltSavedOK = false
    }

    private func applySessionStats() {
        let p = sessionsByPerson[person.trimmingCharacters(in: .whitespaces)] ?? [:]
        modeStats = p.mapValues { ModeStats(sessions: Int($0["sessions"] ?? 0), minutes: $0["minutes"] ?? 0,
                                            trials: Int($0["trials"] ?? 0)) }
    }

    // MARK: zdarzenia

    private func consume(_ data: Data) {
        buffer.append(data)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let line = buffer.subdata(in: buffer.startIndex..<nl)
            buffer.removeSubrange(buffer.startIndex...nl)
            if let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any] { handle(obj) }
        }
    }

    private func handle(_ e: [String: Any]) {
        switch e["type"] as? String {
        case "ready":
            demoFiles = e["demo_files"] as? [String] ?? []
            sendPerson()
            if let d = pendingDemo { pendingDemo = nil; demo(d) }
        case "status":
            state = EngineState(rawValue: e["state"] as? String ?? "") ?? .idle
            message = e["message"] as? String ?? ""
            if state == .streaming { isDemo = e["demo"] as? Bool ?? false }
            if state != .streaming { sessionRecording = false; tilt = nil }
            onChange?()
        case "devices":
            let list = e["devices"] as? [[String: Any]] ?? []
            devices = list.map { Device(name: $0["name"] as? String ?? "?", address: $0["address"] as? String ?? "") }
        case "emo_state":
            emoByPerson = e["by_person"] as? [String: [String: Int]] ?? [:]
            applyEmoCounts()
        case "emo_saved":
            let ok = e["ok"] as? Bool ?? false
            lastEmoMessage = ok ? "zapisano (\(e["clean"] as? Int ?? 0) czystych okien)" : (e["message"] as? String ?? "")
        case "position":
            func num(_ k: String) -> Double { (e[k] as? NSNumber)?.doubleValue ?? 0 }
            position = HeadEye(headX: num("head_x"), headY: num("head_y"), yawDeg: num("head_yaw_deg"),
                               pitchDeg: num("head_pitch_deg"), eyesX: num("eyes_x"),
                               eyesCalibrated: e["eyes_calibrated"] as? Bool ?? false, eyesOk: e["eyes_ok"] as? Bool ?? true)
        case "battery":
            battery = e["level"] as? Int
        case "prediction":
            time = e["t"] as? Double ?? 0
            label = e["label"] as? String ?? "rest"
            confidence = e["confidence"] as? Double ?? 0
            family = e["family"] as? String ?? "rest"
            familyConfidence = e["family_confidence"] as? Double ?? 0
            warmup = e["warmup"] as? Bool ?? false
            let fam = e["families"] as? [String: Double] ?? [:]
            families = ["head", "eyes", "face", "rest"].map { Bar(key: $0, value: fam[$0] ?? 0) }
            let t = e["top"] as? [[String: Any]] ?? []
            top = t.map { Bar(key: $0["label"] as? String ?? "", value: $0["p"] as? Double ?? 0) }
        case "signal":
            var tr = traces
            let eeg = e["eeg"] as? [String: [Double]] ?? [:]
            let gyro = e["gyro"] as? [String: [Double]] ?? [:]
            for (k, v) in eeg { tr[k] = Array(((tr[k] ?? []) + v).suffix(maxPoints)) }
            for (k, v) in gyro { tr["g" + k] = Array(((tr["g" + k] ?? []) + v).suffix(maxPoints)) }
            traces = tr
            let c = e["contact"] as? [String: Int] ?? [:]
            contact = c.mapValues { $0 != 0 }
            lost = e["lost"] as? Double ?? 0
        case "sessions_state":
            let raw = e["by_person"] as? [String: [String: [String: Any]]] ?? [:]
            sessionsByPerson = raw.mapValues { modes in
                modes.mapValues { d in d.compactMapValues { ($0 as? NSNumber)?.doubleValue } }
            }
            applySessionStats()
            onChange?()
        case "session":
            let st = e["state"] as? String ?? ""
            if st == "recording" {
                sessionRecording = true
            } else {
                sessionRecording = false
                let counts = (e["counts"] as? [String: [String: Int]] ?? [:]).values
                    .reduce(into: [String: Int]()) { acc, d in for (k, v) in d { acc[k, default: 0] += v } }
                lastSession = SessionResult(ok: st == "saved", id: e["id"] as? String ?? "",
                                            path: e["path"] as? String ?? "",
                                            duration: e["duration_s"] as? Double ?? 0,
                                            status: e["status"] as? String ?? "", counts: counts,
                                            message: e["message"] as? String ?? "")
            }
            onChange?()
        case "model":
            modelState = e["state"] as? String ?? "none"
            modelMessage = e["message"] as? String ?? ""
            if let n = e["samples"] as? Int { modelSamples = n }
            onChange?()
        case "gesture":
            let g = Gesture(start: e["start"] as? Double ?? 0, end: e["end"] as? Double ?? 0,
                            key: e["key"] as? String ?? "", confidence: e["confidence"] as? Double ?? 0,
                            familyConfidence: e["family_confidence"] as? Double ?? 0)
            gestures.insert(g, at: 0)
            if gestures.count > 200 { gestures.removeLast() }
        case "tilt":
            func degrees(_ v: Any?) -> [String: Double] {
                (v as? [String: Any] ?? [:]).compactMapValues { ($0 as? NSNumber)?.doubleValue }
            }
            let preview = e["preview"] as? [String: Any] ?? [:]
            let dirs = preview["directions"] as? [String: [String: Any]] ?? [:]
            tilt = TiltState(
                angles: degrees(e["angles"]), thresholds: degrees(e["thresholds"]), step: e["step"] as? String,
                counts: (e["counts"] as? [String: Any] ?? [:]).compactMapValues { ($0 as? NSNumber)?.intValue },
                preview: dirs.mapValues { (angle: ($0["angle_deg"] as? NSNumber)?.doubleValue,
                                           threshold: ($0["threshold_deg"] as? NSNumber)?.doubleValue) },
                previewReady: preview["neutral"] is [Any], saved: e["saved"] as? Bool ?? false,
                ready: e["ready"] as? Bool ?? false)
            let now = Date()
            for key in e["gestures"] as? [String] ?? [] { tiltHits.insert(TiltHit(key: key, at: now), at: 0) }
            if tiltHits.count > 12 { tiltHits.removeLast(tiltHits.count - 12) }
        case "tilt_saved":
            tiltSavedOK = e["ok"] as? Bool ?? false
            tiltMessage = tiltSavedOK ? "Zapisano dla czepka \(e["device"] as? String ?? sourceName)."
                : (e["message"] as? String ?? "Nie zapisano.")
        default:
            break
        }
    }
}
