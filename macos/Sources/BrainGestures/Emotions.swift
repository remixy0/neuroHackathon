import AppKit
import SwiftUI

/// Tryb "Emocje": spokoj (krzyzyk) -> wywolanie emocji (wspomnienie albo wlasny material) -> ocena osoby.
/// Proby zapisuja sie osobno od gestow (tools/training/emotions.jsonl), analiza: tools/emotions.py.
enum Emotions {
    static let all: [(key: String, name: String, symbol: String, color: Color)] = [
        ("joy", "Radość", "sun.max.fill", .yellow),
        ("calm", "Spokój", "leaf.fill", .green),
        ("sadness", "Smutek", "cloud.rain.fill", .blue),
        ("anger", "Złość", "flame.fill", .red),
        ("fear", "Strach / napięcie", "exclamationmark.triangle.fill", .orange),
        ("neutral", "Neutralnie", "circle", .gray),
    ]
    static func name(_ k: String) -> String { all.first { $0.key == k }?.name ?? (k == "none" ? "Nic szczególnego" : k) }
    static func symbol(_ k: String) -> String { all.first { $0.key == k }?.symbol ?? "circle" }
    static func color(_ k: String) -> Color { all.first { $0.key == k }?.color ?? .gray }

    /// Instrukcja przywolania wspomnienia (umiarkowane, nie traumatyczne).
    static func recall(_ k: String) -> String {
        switch k {
        case "joy": return "Przypomnij sobie chwilę, w której czułeś/aś dużą radość lub szczęście. Odtwórz ją w myślach jak najdokładniej: gdzie byłeś/aś, kto był obok, co widziałeś/aś i słyszałeś/aś. Pozwól, żeby to uczucie wróciło."
        case "calm": return "Przypomnij sobie miejsce albo chwilę pełnego spokoju i odprężenia. Zobacz je w myślach, usłysz dźwięki, poczuj temperaturę. Oddychaj spokojnie i pozwól, żeby ten spokój wrócił."
        case "sadness": return "Przypomnij sobie sytuację, która wywołała u Ciebie smutek — wybierz coś umiarkowanego, nie najboleśniejszego. Odtwórz ją w myślach i pozwól sobie poczuć ten smutek."
        case "anger": return "Przypomnij sobie sytuację, w której ktoś Cię zdenerwował albo potraktował niesprawiedliwie — coś umiarkowanego. Odtwórz ją w myślach: co się działo, co ktoś powiedział, co wtedy czułeś/aś."
        case "fear": return "Przypomnij sobie moment silnego stresu lub niepokoju, np. tuż przed egzaminem albo wystąpieniem. Odtwórz go w myślach: co się działo i jak reagowało Twoje ciało."
        default: return "Przypomnij sobie zwykłą, codzienną czynność bez emocji, np. jak rano myjesz zęby albo idziesz do sklepu. Odtwórz ją w myślach krok po kroku."
        }
    }
}

struct EmoRating: Equatable {
    var valence = 0      // 1 bardzo nieprzyjemne ... 9 bardzo przyjemne (0 = nie wybrano)
    var arousal = 0      // 1 senność / spokój ... 9 silne pobudzenie
    var intensity = 0    // 1 nic ... 9 bardzo mocno (siła zamierzonej emocji)
    var felt = ""        // co osoba czuła najbardziej
    var complete: Bool { valence > 0 && arousal > 0 && intensity > 0 && !felt.isEmpty }
}

enum EmoPhase: Equatable { case intro, baseline, induction, rating, washout, finished }

struct EmoResult: Equatable, Identifiable {
    let id = UUID()
    let emotion: String
    let person: String
    let rating: EmoRating?   // nil = proba odrzucona albo pominieta
}

struct EmoRun: Equatable {
    var queue: [String]
    var source: String             // "recall" albo "material"
    var baselineS: Double
    var inductionS: Double
    var washoutS: Double
    var note: String
    var index = 0
    var phase: EmoPhase = .intro
    var phaseEnd = Date()
    var results: [EmoResult] = []
    var finished = false
    var current: String? { index < queue.count ? queue[index] : nil }
}

extension Hub {
    func startEmotions(emotions: [String], rounds: Int, source: String, baseline: Double, induction: Double,
                       washout: Double, note: String) {
        guard emoRun == nil || emoRun?.finished == true, !sessionOn, !active.isEmpty, !emotions.isEmpty else { return }
        // w kazdej rundzie wszystkie emocje w losowej kolejnosci; neutralna zawsze pierwsza (rozgrzewka)
        var q: [String] = []
        for _ in 0..<max(1, rounds) {
            let rest = emotions.filter { $0 != "neutral" }.shuffled()
            q += (emotions.contains("neutral") ? ["neutral"] : []) + rest
        }
        emoRun = EmoRun(queue: q, source: source, baselineS: baseline, inductionS: induction, washoutS: washout,
                        note: note)
        emoTask = Task { @MainActor [weak self] in await self?.runEmotions() }
    }

    func stopEmotions() {
        emoTask?.cancel()
        emoTask = nil
        active.forEach { $0.emoStop(ratings: nil) }
        let w = emoRatingWaiter
        emoRatingWaiter = nil
        w?.resume(returning: nil)
        if emoRun != nil { emoRun?.finished = true; emoRun?.phase = .finished }
        voice.stop()
    }

    func skipEmotion() { emoSkip = true }

    func closeEmotionSummary() { if emoRun?.finished == true { emoRun = nil } }

    /// Ocena z planszy (jedna na osobe/czepek) albo nil = odrzuc probe.
    func submitEmotionRatings(_ r: [Int: EmoRating]?) {
        let w = emoRatingWaiter
        emoRatingWaiter = nil
        w?.resume(returning: r)
    }

    /// Czeka `s` sekund; wraca wczesniej przy pominieciu (true) albo przerwaniu.
    @MainActor
    private func waitPhase(_ s: Double) async -> Bool {
        let end = Date().addingTimeInterval(s)
        emoRun?.phaseEnd = end
        while Date() < end {
            if Task.isCancelled { return true }
            if emoSkip { return true }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        return false
    }

    @MainActor
    func runEmotions() async {
        guard let run = emoRun else { return }
        emoRun?.phase = .intro
        await voice.say("Zaczynamy. Patrz na krzyżyk, nie ruszaj głową i staraj się nie mrugać zbyt często. "
                        + "W każdej chwili możesz pominąć emocję albo zakończyć.")
        for (i, emotion) in run.queue.enumerated() {
            if Task.isCancelled || emoRun?.finished != false || active.isEmpty { break }
            emoSkip = false
            emoRun?.index = i
            let targets = active
            // 1. spokoj - tlo tej proby
            emoRun?.phase = .baseline
            targets.forEach { $0.emoStart(emotion, source: run.source, round: i / max(1, Set(run.queue).count) + 1,
                                          note: run.note) }
            voice.speak("Odpręż się i patrz na krzyżyk.")
            if await waitPhase(run.baselineS) {
                targets.forEach { $0.emoStop(ratings: nil) }
                if Task.isCancelled || emoRun?.finished != false { break }
                emoRun?.results.append(contentsOf: targets.map { EmoResult(emotion: emotion, person: $0.person, rating: nil) })
                continue
            }
            // 2. wywolanie emocji
            emoRun?.phase = .induction
            targets.forEach { $0.emoPhase("induction") }
            voice.speak(run.source == "recall" ? Emotions.recall(emotion)
                        : "Włącz materiał: \(Emotions.name(emotion)). Patrz na niego spokojnie, bez ruchu głową.")
            let skipped = await waitPhase(run.inductionS)
            targets.forEach { $0.emoPhase("end") }
            voice.stop()
            if skipped {
                targets.forEach { $0.emoStop(ratings: nil) }
                if Task.isCancelled || emoRun?.finished != false { break }
                emoRun?.results.append(contentsOf: targets.map { EmoResult(emotion: emotion, person: $0.person, rating: nil) })
                continue
            }
            // 3. ocena (osobno kazda osoba)
            emoRun?.phase = .rating
            NSSound(named: "Glass")?.play()
            voice.speak("Oceń, co czułeś.")
            let ratings: [Int: EmoRating]? = await withCheckedContinuation { c in emoRatingWaiter = c }
            for e in targets { e.emoStop(ratings: ratings?[e.slot]) }
            emoRun?.results.append(contentsOf: targets.map {
                EmoResult(emotion: emotion, person: $0.person, rating: ratings?[$0.slot])
            })
            if Task.isCancelled || emoRun?.finished != false { break }
            // 4. przerwa (nienagrywana): powrot do neutralnego stanu
            if i + 1 < run.queue.count {
                emoRun?.phase = .washout
                voice.speak("Przerwa. Policz w myślach od stu w dół co siedem.")
                _ = await waitPhase(run.washoutS)
            }
        }
        emoTask = nil
        guard emoRun != nil, emoRun?.finished == false else { return }
        emoRun?.finished = true
        emoRun?.phase = .finished
        await voice.say("Koniec. Dziękuję.")
    }
}

/// Plansza na cale okno podczas sesji emocji.
struct EmotionOverlay: View {
    @EnvironmentObject var hub: Hub
    @State private var ratings: [Int: EmoRating] = [:]

    var body: some View {
        if let run = hub.emoRun, let emotion = run.current {
            ZStack {
                Color.black
                VStack(spacing: 18) {
                    header(run, emotion)
                    Spacer()
                    switch run.phase {
                    case .rating: ratingSheet(emotion)
                    case .washout: Text("Przerwa\nPolicz w myślach od 100 w dół co 7")
                            .multilineTextAlignment(.center).font(.title2).foregroundStyle(.white.opacity(0.7))
                    case .induction:
                        if run.source == "recall" {
                            Text(Emotions.recall(emotion)).font(.title3).multilineTextAlignment(.center)
                                .foregroundStyle(.white.opacity(0.85)).frame(maxWidth: 640)
                        } else {
                            Text("Włącz przygotowany materiał (\(Emotions.name(emotion).lowercased())) i patrz na niego spokojnie.")
                                .font(.title3).foregroundStyle(.white.opacity(0.85))
                        }
                        cross
                    default:
                        cross
                    }
                    Spacer()
                    HStack {
                        Text("Dane emocji zapisują się osobno od gestów.").font(.callout).foregroundStyle(.white.opacity(0.35))
                        Spacer()
                        if run.phase == .baseline || run.phase == .induction {
                            Button("Pomiń tę emocję") { hub.skipEmotion() }
                        }
                        Button("Zakończ") { hub.stopEmotions() }.keyboardShortcut(.cancelAction)
                    }
                }
                .padding(28)
            }
            .ignoresSafeArea()
            .onChange(of: run.index) { _, _ in ratings = [:] }
        }
    }

    private var cross: some View {
        Text("+").font(.system(size: 64, weight: .light)).foregroundStyle(.white.opacity(0.8))
    }

    private func header(_ run: EmoRun, _ emotion: String) -> some View {
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
            let left = max(0, Int(run.phaseEnd.timeIntervalSince(ctx.date).rounded(.up)))
            let phase: String = {
                switch run.phase {
                case .intro: return "Za chwilę zaczynamy"
                case .baseline: return "Spokój — patrz na krzyżyk · \(left) s"
                case .induction: return "\(Emotions.name(emotion)) · \(left) s"
                case .rating: return "Ocena"
                case .washout: return "Przerwa · \(left) s"
                case .finished: return "Koniec"
                }
            }()
            VStack(spacing: 4) {
                Text(phase).font(.title2.weight(.semibold)).foregroundStyle(.white.opacity(0.85))
                Text("Próba \(run.index + 1) z \(run.queue.count)").font(.callout.monospacedDigit())
                    .foregroundStyle(.white.opacity(0.45))
            }
        }
    }

    private func ratingSheet(_ emotion: String) -> some View {
        let people = hub.active
        let complete = !people.isEmpty && people.allSatisfy { ratings[$0.slot]?.complete == true }
        return VStack(spacing: 14) {
            ForEach(people) { e in
                VStack(alignment: .leading, spacing: 8) {
                    if people.count > 1 { Text(e.person).font(.headline).foregroundStyle(.white) }
                    scale("Jak przyjemne to było?", "bardzo nieprzyjemne", "bardzo przyjemne", e.slot, \.valence)
                    scale("Jak silne pobudzenie?", "senność, spokój", "silne pobudzenie", e.slot, \.arousal)
                    scale("Jak mocno poczułeś/aś: \(Emotions.name(emotion).lowercased())?", "wcale", "bardzo mocno",
                          e.slot, \.intensity)
                    HStack(spacing: 6) {
                        Text("Najbardziej czułem/am:").foregroundStyle(.white.opacity(0.8))
                        ForEach(Emotions.all.map(\.key) + ["none"], id: \.self) { k in
                            let on = ratings[e.slot]?.felt == k
                            Button(Emotions.name(k)) { ratings[e.slot, default: EmoRating()].felt = k }
                                .buttonStyle(.bordered).tint(on ? .accentColor : .gray)
                        }
                    }
                }
                .padding(14)
                .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
            }
            HStack {
                Button("Odrzuć próbę") { hub.submitEmotionRatings(nil) }
                Button("Zapisz") { hub.submitEmotionRatings(ratings) }
                    .buttonStyle(.borderedProminent).disabled(!complete).keyboardShortcut(.defaultAction)
            }
        }
        .frame(maxWidth: 860)
    }

    private func scale(_ title: String, _ lo: String, _ hi: String, _ slot: Int,
                       _ key: WritableKeyPath<EmoRating, Int>) -> some View {
        HStack(spacing: 6) {
            Text(title).foregroundStyle(.white.opacity(0.8)).frame(width: 260, alignment: .leading)
            Text(lo).font(.caption).foregroundStyle(.white.opacity(0.45)).frame(width: 110, alignment: .trailing)
            ForEach(1...9, id: \.self) { v in
                let on = (ratings[slot]?[keyPath: key] ?? 0) == v
                Button("\(v)") { ratings[slot, default: EmoRating()][keyPath: key] = v }
                    .buttonStyle(.bordered).tint(on ? .accentColor : .gray).frame(width: 34)
            }
            Text(hi).font(.caption).foregroundStyle(.white.opacity(0.45)).frame(width: 110, alignment: .leading)
        }
    }
}

/// Ustawienia sesji emocji.
struct EmotionSetupCard: View {
    @EnvironmentObject var hub: Hub
    let allowed: Bool
    @AppStorage("emoSelected") private var selected = "joy,calm,sadness,anger,fear,neutral"
    @AppStorage("emoSource") private var source = "recall"
    @AppStorage("emoBaseline") private var baseline = 20
    @AppStorage("emoInduction") private var induction = 60
    @AppStorage("emoWashout") private var washout = 20
    @AppStorage("emoRounds") private var rounds = 1
    @State private var note = ""

    private var chosen: [String] { Emotions.all.map(\.key).filter { selected.split(separator: ",").map(String.init).contains($0) } }

    private func toggle(_ k: String) {
        var s = Set(selected.split(separator: ",").map(String.init))
        if s.contains(k) { s.remove(k) } else { s.insert(k) }
        selected = Emotions.all.map(\.key).filter { s.contains($0) }.joined(separator: ",")
    }

    var body: some View {
        let perTrial = Double(baseline + induction + washout) + 20
        let minutes = Int((perTrial * Double(chosen.count * rounds) / 60).rounded(.up))
        HStack(alignment: .top, spacing: 18) {
            Image(systemName: "heart.text.square.fill").font(.system(size: 40)).foregroundStyle(.pink)
            VStack(alignment: .leading, spacing: 8) {
                Text("Zbieranie danych o emocjach").font(.title2.bold())
                Text("Każda próba: spokój (krzyżyk) → wywołanie emocji → ocena osoby (przyjemność, pobudzenie, siła). "
                     + "Nagrywany jest sygnał spokoju i wywołania; ocena i przerwa nie. Wybieraj wspomnienia umiarkowane — "
                     + "w każdej chwili można pominąć emocję albo zakończyć. Dane nie wpływają na rozpoznawanie gestów.")
                    .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 6) {
                    ForEach(Emotions.all, id: \.key) { em in
                        let on = chosen.contains(em.key)
                        let n = hub.active.map { $0.emoCounts[em.key] ?? 0 }.min() ?? 0
                        Button { toggle(em.key) } label: {
                            Label("\(em.name) · \(n)", systemImage: em.symbol)
                        }
                        .buttonStyle(.bordered).tint(on ? em.color : .gray).opacity(on ? 1 : 0.6)
                        .help("Zapisanych prób tej emocji: \(n)")
                    }
                }
                Picker("Źródło emocji", selection: $source) {
                    Text("Wspomnienie (instrukcja na ekranie i głosem)").tag("recall")
                    Text("Własny materiał (film, muzyka obok)").tag("material")
                }
                .frame(maxWidth: 520)
                HStack(spacing: 14) {
                    Stepper("Spokój: \(baseline) s", value: $baseline, in: 10...60, step: 5)
                    Stepper("Emocja: \(induction) s", value: $induction, in: 30...180, step: 10)
                    Stepper("Przerwa: \(washout) s", value: $washout, in: 10...60, step: 5)
                    Stepper("Rundy: \(rounds)", value: $rounds, in: 1...3)
                }
                .font(.callout)
                HStack {
                    TextField("Notatka (np. jaki materiał, samopoczucie)", text: $note).frame(maxWidth: 420)
                    Text("·  \(chosen.count * rounds) prób, ok. \(minutes) min").foregroundStyle(.secondary).monospacedDigit()
                }
            }
            Spacer()
            Button {
                hub.startEmotions(emotions: chosen, rounds: rounds, source: source, baseline: Double(baseline),
                                  induction: Double(induction), washout: Double(washout), note: note)
            } label: {
                Label("Start", systemImage: "play.fill").font(.title3.bold()).frame(width: 120, height: 34)
            }
            .buttonStyle(.borderedProminent)
            .disabled(chosen.isEmpty || !allowed || hub.busy)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
    }
}

/// Wynik sesji emocji.
struct EmotionSummaryCard: View {
    @EnvironmentObject var hub: Hub
    let run: EmoRun

    var body: some View {
        let saved = run.results.filter { $0.rating != nil }.count
        HStack(alignment: .top, spacing: 18) {
            Image(systemName: "checkmark.circle.fill").font(.system(size: 38)).foregroundStyle(.green)
            VStack(alignment: .leading, spacing: 6) {
                Text("Zapisano \(saved) prób emocji").font(.title2.bold())
                ScrollView {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(run.results) { r in
                            HStack(spacing: 8) {
                                Image(systemName: Emotions.symbol(r.emotion)).foregroundStyle(Emotions.color(r.emotion))
                                    .frame(width: 18)
                                Text(Emotions.name(r.emotion)).frame(width: 130, alignment: .leading)
                                if hub.active.count > 1 { Text(r.person).frame(width: 90, alignment: .leading) }
                                if let x = r.rating {
                                    Text("przyjemność \(x.valence) · pobudzenie \(x.arousal) · siła \(x.intensity) · czuł(a): \(Emotions.name(x.felt))")
                                        .foregroundStyle(.secondary)
                                } else {
                                    Text("pominięta / odrzucona").foregroundStyle(.orange)
                                }
                            }
                            .font(.callout)
                        }
                    }
                }
                .frame(maxHeight: 140)
                Text("Analiza zebranych danych: tools/emotions.py (asymetria alfa, moce pasm, odróżnianie walencji).")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Zamknij") { hub.closeEmotionSummary() }.buttonStyle(.borderedProminent)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
    }
}
