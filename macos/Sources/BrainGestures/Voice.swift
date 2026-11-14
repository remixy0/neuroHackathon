import AVFoundation

/// Polskie polecenia glosowe. `say` czeka, az wypowiedz sie skonczy.
final class Voice: NSObject, AVSpeechSynthesizerDelegate {
    private let synth = AVSpeechSynthesizer()
    private var current: AVSpeechUtterance?
    private var waiter: CheckedContinuation<Void, Never>?
    private var token = 0

    override init() {
        super.init()
        synth.delegate = self
    }

    private func utterance(_ text: String) -> AVSpeechUtterance {
        let u = AVSpeechUtterance(string: text)
        u.voice = AVSpeechSynthesisVoice(language: "pl-PL")
        return u
    }

    /// Mowi bez czekania.
    func speak(_ text: String) {
        stop()
        let u = utterance(text)
        current = u
        synth.speak(u)
    }

    /// Mowi i wraca po zakonczeniu wypowiedzi (z zapasowym limitem czasu).
    @MainActor
    func say(_ text: String) async {
        stop()
        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            token += 1
            let my = token
            waiter = c
            let u = utterance(text)
            current = u
            synth.speak(u)
            let limit = 2.0 + Double(text.split(separator: " ").count) * 0.7
            DispatchQueue.main.asyncAfter(deadline: .now() + limit) { [weak self] in
                if self?.token == my { self?.finish() }
            }
        }
    }

    func stop() {
        current = nil
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        finish()
    }

    private func finish() {
        let w = waiter
        waiter = nil
        w?.resume()
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        DispatchQueue.main.async { [weak self] in
            guard let self, u === self.current else { return }
            self.current = nil
            self.finish()
        }
    }
}
