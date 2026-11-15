import SwiftUI

enum Labels {
    static let names: [String: String] = [
        "rest": "Spoczynek", "blink": "Mrugnięcie", "double_blink": "Podwójne mrugnięcie",
        "look_left": "Spojrzenie w lewo", "look_right": "Spojrzenie w prawo",
        "mouth_left": "Usta w lewo", "mouth_right": "Usta w prawo",
        "jaw": "Otwarcie szczęki", "head_left": "Głowa w lewo", "head_right": "Głowa w prawo",
        "head_up": "Głowa w górę", "head_down": "Głowa w dół", "frown": "Zmarszczenie czoła",
    ]
    static let families: [String: String] = [
        "head": "Ruch głowy", "eyes": "Oczy", "face": "Mięśnie twarzy", "rest": "Spoczynek",
    ]
    static let symbols: [String: String] = [
        "rest": "pause.circle", "blink": "eye.slash", "double_blink": "eye.slash",
        "look_left": "arrow.left", "look_right": "arrow.right",
        "mouth_left": "mouth", "mouth_right": "mouth", "jaw": "mouth.fill",
        "head_left": "arrow.turn.up.left", "head_right": "arrow.turn.up.right",
        "head_up": "arrow.up.to.line", "head_down": "arrow.down.to.line", "frown": "eyebrow",
    ]

    /// Polecenia czytane na glos osobie w czepku
    static let commands: [String: String] = [
        "rest": "Siedź spokojnie", "blink": "Mrugnij", "double_blink": "Mrugnij dwa razy",
        "look_left": "Spójrz w lewo", "look_right": "Spójrz w prawo",
        "mouth_left": "Usta w lewo", "mouth_right": "Usta w prawo",
        "jaw": "Otwórz szczękę", "head_left": "Obróć głowę w lewo", "head_right": "Obróć głowę w prawo",
        "head_up": "Głowa w górę", "head_down": "Głowa w dół", "frown": "Zmarszcz czoło",
    ]

    /// Kafelki ekranu Trening, w grupach
    static let trainingGroups: [(title: String, family: String, keys: [String])] = [
        ("Oczy", "eyes", ["double_blink", "look_left", "look_right"]),
        ("Twarz", "face", ["jaw", "frown"]),
        ("Głowa", "head", ["head_left", "head_right", "head_up", "head_down"]),
        ("Spoczynek (dłuższe nagranie)", "rest", ["rest"]),
    ]
    static let trainingGoal = 10

    /// Spojrzenia prowadzone kropka na ekranie: kierunek, w ktory kropka odjezdza (x > 0 w prawo, y > 0 w gore).
    static let dotTarget: [String: CGPoint] = ["look_left": CGPoint(x: -1, y: 0), "look_right": CGPoint(x: 1, y: 0)]
    static let eyeLabels = ["look_left", "look_right"]

    /// Polecenie czytane na glos / pokazywane przed proba. Przy kropce bez kierunku,
    /// zeby oko ruszylo dopiero za kropka (wtedy znamy chwile ruchu).
    static func prompt(_ key: String) -> String {
        dotTarget[key] != nil ? "Patrz na kropkę" : (commands[key] ?? name(key))
    }

    static func name(_ key: String) -> String {
        if key.hasPrefix("?") { return (families[String(key.dropFirst())] ?? key) + " (rodzaj niepewny)" }
        return names[key] ?? key
    }

    static func family(of key: String) -> String {
        let k = key.hasPrefix("?") ? String(key.dropFirst()) : key
        if families[k] != nil { return k }
        if k.hasPrefix("head") { return "head" }
        if k.hasPrefix("look") || k.hasPrefix("eyes") || k.hasSuffix("blink") { return "eyes" }
        if k.hasPrefix("mouth") || k == "jaw" || k == "frown" { return "face" }
        return "rest"
    }

    static func symbol(_ key: String) -> String {
        if let s = symbols[key] { return s }
        switch family(of: key) {
        case "head": return "person.crop.circle"
        case "eyes": return "eye"
        case "face": return "face.smiling"
        default: return "pause.circle"
        }
    }

    static func color(family: String) -> Color {
        switch family {
        case "head": return .blue
        case "eyes": return .purple
        case "face": return .orange
        default: return .gray
        }
    }

    static func percent(_ v: Double) -> String { "\(Int((v * 100).rounded()))%" }

    static func clock(_ t: Double) -> String {
        let s = max(0, Int(t))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}
