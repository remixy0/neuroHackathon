import AppKit
import SwiftUI

/// Tryby treningu: kazda kategoria ruchu ma wlasna sesje. Sesja = ciagly zapis surowego sygnalu czepka
/// + znaczniki czasu kazdego bodzca (silnik: tools/session_recorder.py -> training/sessions/).
enum TrainMode: String, CaseIterable, Identifiable {
    case eyes, blink, head, frown, jaw
    var id: String { rawValue }

    var title: String {
        switch self {
        case .eyes: return "Oczy"
        case .blink: return "Mruganie"
        case .head: return "Głowa"
        case .frown: return "Czoło"
        case .jaw: return "Szczęka"
        }
    }

    var symbol: String {
        switch self {
        case .eyes: return "eye"
        case .blink: return "eye.slash"
        case .head: return "arrow.up.and.down.and.arrow.left.and.right"
        case .frown: return "eyebrow"
        case .jaw: return "mouth.fill"
        }
    }

    var family: String {
        switch self {
        case .eyes, .blink: return "eyes"
        case .head: return "head"
        case .frown, .jaw: return "face"
        }
    }

    var defaultMinutes: Int { self == .eyes || self == .head ? 2 : 1 }

    /// Polecenie czytane na glos na poczatku sesji (zapisywane tez w danych).
    var instructions: String {
        switch self {
        case .eyes:
            return "Patrz na żółtą kropkę i podążaj za nią samym wzrokiem. Głowa nieruchomo. "
                + "Kropka skacze w bok i wraca albo płynnie jeździ. Mrugaj najlepiej wtedy, gdy kropka stoi na środku."
        case .blink:
            return "Patrz na krzyżyk. Po każdym sygnale mrugnij raz, wyraźnie. Między sygnałami staraj się nie mrugać."
        case .head:
            return "Najpierw zobaczysz i usłyszysz kierunek. Na sygnał obróć albo pochyl głowę w tę stronę i zostań tak. "
                + "Na drugi sygnał wróć głową do środka."
        case .frown:
            return "Na sygnał mocno zmarszcz czoło albo unieś brwi i trzymaj. Na drugi sygnał rozluźnij twarz."
        case .jaw:
            return "Na sygnał szeroko otwórz usta, opuść szczękę i trzymaj. Na drugi sygnał zamknij usta i rozluźnij."
        }
    }

    /// Opis trybu na ekranie ustawien.
    var summary: String {
        switch self {
        case .eyes:
            return "Kropka jeździ tylko na boki: skacze w lewo lub w prawo (różna odległość) i wraca na środek, "
                + "a co jakiś czas płynnie przejeżdża od krawędzi do krawędzi. Pozycja kropki zapisuje się dla każdej próbki sygnału."
        case .blink:
            return "Krzyżyk na środku i piknięcie co 2,5–4,5 s (losowo). Na każde piknięcie — jedno wyraźne mrugnięcie."
        case .head:
            return "Kierunek (strzałka + głos), po chwili piknięcie = ruch głowy i przytrzymanie 1,5 s, drugi dźwięk = powrót. "
                + "Lewo, prawo, góra, dół po równo, w losowej kolejności."
        case .frown:
            return "Piknięcie = zmarszcz czoło i trzymaj 2 s, drugi dźwięk = rozluźnij. Przerwy 2,5–4 s."
        case .jaw:
            return "Piknięcie = otwórz szeroko usta i trzymaj 1,5 s, drugi dźwięk = zamknij. Przerwy 2,5–4 s."
        }
    }
}

/// Co widac na planszy sesji.
enum SessionDisplay: Equatable {
    case fixation                 // krzyzyk (spoczynek / mruganie)
    case dot                      // kropka (tryb oczu)
    case text(String, Bool)       // napis, czy wyrozniony (moment ruchu)
    case arrow(String, String)    // etykieta kierunku (head_left...), napis
}

/// Odcinek ruchu kropki: x w -1...1 (0 = srodek, -1 lewa krawedz, +1 prawa).
struct DotSegment: Equatable {
    let start: Date
    let from: Double
    let to: Double
    let duration: Double
    let smooth: Bool              // true: smoothstep (skok), false: liniowo (plynny przejazd)

    func x(at t: Date) -> Double {
        let u = min(1, max(0, t.timeIntervalSince(start) / max(duration, 1e-6)))
        let e = smooth ? u * u * (3 - 2 * u) : u
        return from + (to - from) * e
    }
}

struct TrainRun: Equatable {
    let mode: TrainMode
    let started: Date
    let minutes: Double
    var end: Date                 // koniec czesci z probami (ustalany po spoczynku na poczatku)
    var phase = "Start"           // krotki opis etapu (pasek u gory)
    var display: SessionDisplay = .fixation
    var flash: Date?              // chwila ostatniego sygnalu (blysk na planszy)
    var trials = 0
    var counts: [String: Int] = [:]
    var finished = false
    var stoppedEarly = false
}

/// Wszystkie czepki razem: wspolne polecenia glosowe i sesje treningowe.
/// Kazdy podlaczony czepek nagrywa te sama sesje jednoczesnie, ale zapisuje ja dla swojej osoby.
final class Hub: ObservableObject {
    let engines: [Engine]
    let voice = Voice()

    @Published var secondSlot: Bool {
        didSet {
            UserDefaults.standard.set(secondSlot, forKey: "secondSlot")
            if secondSlot { engines[1].start() } else { engines[1].stop() }
        }
    }
    /// Trwajaca (albo zakonczona, do podsumowania) sesja treningowa.
    @Published var run: TrainRun?
    @Published var dot: DotSegment?
    private var runTask: Task<Void, Never>?
    private var runTargets: [Engine] = []
    /// Tryb "Emocje": sesja spokoj -> wywolanie emocji -> ocena (dane osobno od gestow).
    @Published var emoRun: EmoRun?
    var emoTask: Task<Void, Never>?
    var emoRatingWaiter: CheckedContinuation<[Int: EmoRating]?, Never>?
    var emoSkip = false

    init() {
        engines = [Engine(slot: 1), Engine(slot: 2)]
        secondSlot = UserDefaults.standard.bool(forKey: "secondSlot")
        for e in engines {
            e.onChange = { [weak self] in self?.engineChanged() }
        }
    }

    var slots: [Engine] { secondSlot ? engines : [engines[0]] }
    var active: [Engine] { slots.filter(\.isStreaming) }
    var sessionOn: Bool { run.map { !$0.finished } ?? false }
    var busy: Bool { sessionOn || (emoRun.map { !$0.finished } ?? false) }

    /// Te same imiona w dwoch czepkach pomieszalyby dane.
    var duplicatePeople: Bool {
        let names = active.map { $0.person.trimmingCharacters(in: .whitespaces).lowercased() }
        return Set(names).count < names.count
    }

    func start() {
        engines[0].start()
        if secondSlot { engines[1].start() }
    }

    func stopAll() {
        if sessionOn { stopSession() }
        engines.forEach { $0.stop() }
    }

    /// Tylko do testow aplikacji: BRAINGESTURES_TEST_SESSION="head:0.4" startuje sesje po polaczeniu.
    private var testSession = ProcessInfo.processInfo.environment["BRAINGESTURES_TEST_SESSION"]

    private func engineChanged() {
        objectWillChange.send()
        if let t = testSession, !active.isEmpty, !busy {
            testSession = nil
            let parts = t.split(separator: ":")
            if let m = parts.first.flatMap({ TrainMode(rawValue: String($0)) }) {
                let minutes = parts.count > 1 ? Double(parts[1]) ?? 0.5 : 0.5
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                    self?.startSession(m, minutes: minutes)
                }
            }
        }
        if sessionOn, active.isEmpty { stopSession() }
        if let r = emoRun, !r.finished, active.isEmpty { stopEmotions() }
    }

    // MARK: sesja treningowa

    func startSession(_ mode: TrainMode, minutes: Double) {
        guard !busy, !active.isEmpty else { return }
        let now = Date()
        run = TrainRun(mode: mode, started: now, minutes: minutes,
                       end: now.addingTimeInterval(15 + baselineS + minutes * 60))
        runTargets = active
        let proto = protocolInfo(mode, minutes: minutes)
        for e in runTargets {
            e.sessionStart(mode: mode.rawValue, protocolInfo: proto, instructions: mode.instructions, at: now)
        }
        runTask = Task { @MainActor [weak self] in await self?.runSession() }
    }

    /// Przerwanie przez operatora: dane do tej chwili zostaja zapisane (status "stopped_early").
    func stopSession() {
        guard sessionOn else { return }
        runTask?.cancel()
        runTask = nil
        voice.stop()
        for e in runTargets { e.sessionStop(status: "stopped_early") }
        run?.finished = true
        run?.stoppedEarly = true
        dot = nil
    }

    func closeSessionSummary() { if run?.finished == true { run = nil } }

    // stale protokolow (zapisywane w session.json -> protocol)
    let baselineS = 10.0
    static let dotMargin = 50.0
    static let dotDiameter = 36.0

    private func protocolInfo(_ mode: TrainMode, minutes: Double) -> [String: Any] {
        var p: [String: Any] = ["mode": mode.rawValue, "planned_duration_s": minutes * 60, "baseline_s": baselineS,
                                "people_recorded_together": active.map(\.person),
                                "sounds": ["cue": "macOS system sound 'Tink' (GO)", "return": "macOS system sound 'Pop'",
                                           "end": "'Glass'"]]
        switch mode {
        case .eyes:
            p["jump_probability"] = 0.7
            p["jump"] = ["wait_center_s": [1.0, 2.0], "amplitude": [0.5, 1.0], "move_s": 0.15, "easing": "smoothstep",
                         "hold_s": [1.2, 1.8]]
            p["sweep"] = ["speed_per_s": 0.8, "easing": "linear", "pause_at_edge_s": 0.3,
                          "path": "centre -> random edge -> opposite edge -> centre"]
            var screen: [String: Any] = ["dot_diameter_px": Self.dotDiameter, "margin_px": Self.dotMargin,
                                         "x_to_px": "x_px = width/2 + x * (width/2 - margin_px), y = height/2"]
            if let w = NSApp.keyWindow ?? NSApp.mainWindow ?? NSApp.windows.first(where: \.isVisible) {
                screen["window_px"] = [w.contentLayoutRect.width, w.contentLayoutRect.height]
                screen["full_screen"] = w.styleMask.contains(.fullScreen)
            }
            if let s = NSScreen.main {
                screen["screen_px"] = [s.frame.width, s.frame.height]
                let id = (s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value
                if let id { let mm = CGDisplayScreenSize(id); screen["screen_mm"] = [mm.width, mm.height] }
            }
            p["screen"] = screen
        case .blink:
            p["interval_s"] = [2.5, 4.5]
        case .head:
            p["pause_s"] = [1.5, 2.5]; p["announce_to_cue_s"] = 1.2; p["hold_s"] = 1.5; p["after_return_s"] = 1.0
            p["order"] = "balanced: each round the 4 directions in random order"
        case .frown:
            p["pause_s"] = [2.5, 4.0]; p["hold_s"] = 2.0
        case .jaw:
            p["pause_s"] = [2.5, 4.0]; p["hold_s"] = 1.5
        }
        return p
    }

    /// Znacznik czasu w danych wszystkich nagrywanych czepkow (ten sam czas unix).
    private func event(_ name: String, label: String? = nil, trial: Int? = nil, x: Double? = nil, xTo: Double? = nil,
                       duration: Double? = nil, details: [String: Any]? = nil, at date: Date = Date()) {
        for e in runTargets {
            e.sessionEvent(name, label: label, trial: trial, x: x, xTo: xTo, duration: duration, details: details, at: date)
        }
    }

    /// Czeka s sekund; false = sesja przerwana.
    @MainActor
    private func wait(_ s: Double) async -> Bool {
        guard s > 0 else { return !Task.isCancelled && sessionOn }
        try? await Task.sleep(nanoseconds: UInt64(s * 1e9))
        return !Task.isCancelled && sessionOn
    }

    private var timeLeft: Bool { (run.map { Date() < $0.end } ?? false) && sessionOn }

    private func cueSound() { NSSound(named: "Tink")?.play() }
    private func returnSound() { NSSound(named: "Pop")?.play() }

    @MainActor
    private func runSession() async {
        guard let mode = run?.mode else { return }
        run?.phase = "Instrukcja"
        run?.display = mode == .eyes ? .dot : .text("Słuchaj polecenia", false)
        if mode == .eyes { dot = DotSegment(start: Date(), from: 0, to: 0, duration: 0, smooth: false) }
        event("instruction", details: ["text": mode.instructions, "spoken": true])
        await voice.say(mode.instructions)
        guard await wait(0.5) else { return }

        // spoczynek na poczatku kazdej sesji
        run?.phase = "Spoczynek — siedź spokojnie, patrz na środek"
        run?.display = mode == .eyes ? .dot : .fixation
        event("baseline_start", label: "rest")
        guard await wait(baselineS) else { return }
        event("baseline_end", label: "rest")
        if let m = run?.minutes { run?.end = Date().addingTimeInterval(m * 60) }

        switch mode {
        case .eyes: await runEyes()
        case .blink: await runBlink()
        case .head: await runHead()
        case .frown: await runHold(label: "frown", now: "ZMARSZCZ CZOŁO", relax: "Rozluźnij", hold: 2.0)
        case .jaw: await runHold(label: "jaw", now: "OTWÓRZ USTA", relax: "Zamknij i rozluźnij", hold: 1.5)
        }
        guard sessionOn, !Task.isCancelled else { return }
        for e in runTargets { e.sessionStop(status: "complete") }
        run?.finished = true
        dot = nil
        runTask = nil
        NSSound(named: "Glass")?.play()
        await voice.say("Koniec. Dziękuję.")
    }

    private func count(_ label: String) {
        run?.trials += 1
        run?.counts[label, default: 0] += 1
    }

    @MainActor
    private func runBlink() async {
        var trial = 0
        run?.phase = "Mrugnij raz po każdym piknięciu"
        while timeLeft {
            run?.display = .fixation
            guard await wait(Double.random(in: 2.5...4.5)), timeLeft else { return }
            trial += 1
            let t = Date()
            event("cue", label: "blink", trial: trial, details: ["sound": "Tink"], at: t)
            cueSound()
            run?.flash = t
            count("blink")
        }
    }

    @MainActor
    private func runHold(label: String, now: String, relax: String, hold: Double) async {
        var trial = 0
        while timeLeft {
            run?.phase = "Przerwa"
            run?.display = .text(relax, false)
            guard await wait(Double.random(in: 2.5...4.0)), timeLeft else { return }
            trial += 1
            let t = Date()
            event("cue", label: label, trial: trial, details: ["sound": "Tink", "text": now], at: t)
            cueSound()
            run?.flash = t
            run?.phase = "Teraz"
            run?.display = .text(now, true)
            count(label)
            guard await wait(hold) else { return }
            event("return", label: "relax", trial: trial, details: ["sound": "Pop", "text": relax])
            returnSound()
            run?.display = .text(relax, false)
        }
    }

    private static let headWords = ["head_left": "w lewo", "head_right": "w prawo", "head_up": "w górę",
                                    "head_down": "w dół"]

    @MainActor
    private func runHead() async {
        var trial = 0
        var queue: [String] = []
        while timeLeft {
            if queue.isEmpty { queue = ["head_left", "head_right", "head_up", "head_down"].shuffled() }
            let label = queue.removeFirst()
            let word = Self.headWords[label] ?? label
            run?.phase = "Przerwa — głowa na środku"
            run?.display = .fixation
            guard await wait(Double.random(in: 1.5...2.5)), timeLeft else { return }
            trial += 1
            run?.phase = "Przygotuj się"
            run?.display = .arrow(label, "Następnie: \(word)")
            event("announce", label: label, trial: trial, details: ["text": "Następnie: \(word)", "voice": word])
            voice.speak(word)
            guard await wait(1.2) else { return }
            let t = Date()
            event("cue", label: label, trial: trial, details: ["sound": "Tink"], at: t)
            cueSound()
            run?.flash = t
            run?.phase = "Teraz"
            run?.display = .arrow(label, "TERAZ — \(word)")
            count(label)
            guard await wait(1.5) else { return }
            event("return", label: "center", trial: trial, details: ["sound": "Pop"])
            returnSound()
            run?.display = .text("Wróć do środka", false)
            guard await wait(1.0) else { return }
        }
    }

    /// Przesuwa kropke i zapisuje ruch (x od, x do, czas, rodzaj krzywej).
    @MainActor
    private func move(to x: Double, duration: Double, smooth: Bool, label: String, trial: Int, kind: String) {
        let from = dot.map { $0.x(at: Date()) } ?? 0
        let t = Date()
        dot = DotSegment(start: t, from: from, to: x, duration: duration, smooth: smooth)
        event("stim_move", label: label, trial: trial, x: from, xTo: x, duration: duration,
              details: ["kind": kind, "easing": smooth ? "smoothstep" : "linear"], at: t)
    }

    @MainActor
    private func runEyes() async {
        var trial = 0
        var sides: [String: Int] = ["look_left": 0, "look_right": 0]
        run?.display = .dot
        while timeLeft {
            trial += 1
            if Double.random(in: 0..<1) < 0.7 {
                // skok w bok i powrot (kierunek: ten, ktorego bylo mniej)
                run?.phase = "Kropka skacze — podążaj wzrokiem"
                guard await wait(Double.random(in: 1.0...2.0)), timeLeft else { return }
                let label = sides["look_left"]! == sides["look_right"]! ? ["look_left", "look_right"].randomElement()!
                    : (sides["look_left"]! < sides["look_right"]! ? "look_left" : "look_right")
                let amp = Double.random(in: 0.5...1.0)
                move(to: label == "look_left" ? -amp : amp, duration: 0.15, smooth: true, label: label, trial: trial,
                     kind: "jump")
                sides[label, default: 0] += 1
                count(label)
                run?.flash = Date()
                guard await wait(0.15 + Double.random(in: 1.2...1.8)) else { return }
                move(to: 0, duration: 0.15, smooth: true, label: "center", trial: trial, kind: "jump")
                guard await wait(0.15) else { return }
            } else {
                // plynny przejazd: srodek -> krawedz -> druga krawedz -> srodek
                run?.phase = "Kropka jedzie — podążaj wzrokiem"
                guard await wait(Double.random(in: 1.0...1.5)), timeLeft else { return }
                let first = Bool.random() ? -1.0 : 1.0
                let speed = 0.8
                count("pursuit")
                for target in [first, -first, 0.0] {
                    let from = dot.map { $0.x(at: Date()) } ?? 0
                    let d = abs(target - from) / speed
                    move(to: target, duration: d, smooth: false, label: "pursuit", trial: trial, kind: "sweep")
                    guard await wait(d + (target == 0 ? 0 : 0.3)) else { return }
                }
            }
        }
    }
}
