import SwiftUI
#if canImport(HaloCore)
import HaloCore
#endif

enum Retro {
    static let background = Color(red: 0.21, green: 0.24, blue: 0.25)
    static let panel = Color(red: 0.09, green: 0.11, blue: 0.11)
    static let rim = Color(red: 0.28, green: 0.31, blue: 0.32)
    static let ink = Color(red: 0.73, green: 0.72, blue: 0.67)
    static let accent = Color(red: 1, green: 0.19, blue: 0.32)
    static let red = Color(red: 0.74, green: 0, blue: 0.13)
    static let black = Color(red: 0.045, green: 0.055, blue: 0.055)
}

struct ControllerView: View {
    let player: Int
    let sent: Int
    let onPlayer: (Int) -> Void
    let onClose: () -> Void
    let onPress: (PadButton) -> Void
    var body: some View {
        GeometryReader { geometry in
            let wide = geometry.size.width > geometry.size.height
            VStack(spacing: 12) {
                HStack(spacing: 8) {
                    HStack(spacing: 2) {
                        ForEach(1...2, id: \.self) { number in
                            Button { if number != player { onPlayer(number) } } label: {
                                Text("Player \(number)").font(.system(.subheadline, design: .rounded).bold())
                                    .padding(.horizontal, 12).frame(minHeight: 44)
                                    .background(player == number ? Color(red: 0.14, green: 0.14, blue: 0.36) : .clear, in: Capsule())
                            }.buttonStyle(.plain).accessibilityAddTraits(player == number ? [.isSelected] : [])
                        }
                    }.padding(4).background(Retro.rim, in: Capsule())
                    Spacer(minLength: 0)
                    Circle().fill(.green).frame(width: 9, height: 9).accessibilityLabel("Połączono")
                    if geometry.size.width > 430 { Text("ONLINE · \(sent)").font(.system(.caption, design: .monospaced).bold()).foregroundStyle(Retro.ink).accessibilityLabel("Połączono. Wysłano \(sent) zdarzeń") }
                    Button(action: onClose) { Image(systemName: "xmark").font(.headline).frame(width: 44, height: 44) }
                        .buttonStyle(.plain).accessibilityLabel("Zakończ sesję")
                }
                GeometryReader { pad in
                    let side = min(wide ? pad.size.width * 0.29 : pad.size.width * 0.62, wide ? pad.size.height - 24 : pad.size.height * 0.49, 300)
                    if wide {
                        HStack(spacing: 12) {
                            dpad(size: max(144, side)).frame(maxWidth: .infinity)
                            systemButtons(horizontal: false).frame(maxWidth: .infinity)
                            actions(size: max(48, min(100, (pad.size.height - 72) / 2, (pad.size.width / 3 - 70) / 2))).frame(maxWidth: .infinity)
                        }.padding(12).frame(width: pad.size.width, height: pad.size.height)
                    } else {
                        VStack(spacing: 12) {
                            HStack { Spacer(); dpad(size: max(144, side)); Spacer() }.frame(maxHeight: .infinity)
                            actions(size: max(48, min(88, pad.size.height * 0.16, (pad.size.width - 110) / 3)), horizontal: true).frame(maxHeight: .infinity)
                            systemButtons(horizontal: true)
                        }.padding(16).frame(width: pad.size.width, height: pad.size.height)
                    }
                }
                .background(Retro.panel, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Retro.rim, lineWidth: 6))
            }.padding(12).foregroundStyle(Retro.ink)
        }
        .accessibilityIdentifier("manual-controller")
    }
    private func dpad(size: CGFloat) -> some View {
        let unit = size / 3
        return VStack(spacing: 0) {
            direction(.up, unit: unit)
            HStack(spacing: 0) {
                direction(.left, unit: unit)
                Circle().fill(Color.black.opacity(0.35)).frame(width: unit * 0.45, height: unit * 0.45)
                    .frame(width: unit, height: unit).background(Retro.black)
                direction(.right, unit: unit)
            }
            direction(.down, unit: unit)
        }.frame(width: size, height: size)
    }
    private func direction(_ button: PadButton, unit: CGFloat) -> some View {
        Button { onPress(button) } label: {
            Text(button.label).font(.system(size: unit * 0.43, weight: .bold))
                .frame(width: unit, height: unit).background(Retro.black)
        }.buttonStyle(PadPressStyle()).accessibilityLabel(button.rawValue)
    }
    private func actions(size: CGFloat, horizontal: Bool = false) -> some View {
        Group {
            if horizontal {
                HStack(spacing: 18) { action(.x, size: size); action(.b, size: size); action(.a, size: size) }
            } else {
                HStack(spacing: 14) { action(.x, size: size); VStack(spacing: 20) { action(.a, size: size); action(.b, size: size) } }
            }
        }
    }
    private func action(_ button: PadButton, size: CGFloat) -> some View {
        Button { onPress(button) } label: {
            Text(button.label).font(.system(size: size * 0.38, weight: .black, design: .rounded))
                .foregroundStyle(button == .x ? Retro.ink : .white)
                .frame(width: size, height: size)
                .background(button == .x ? Retro.rim : Retro.red, in: Circle())
                .shadow(color: .black.opacity(0.4), radius: 0, y: 6)
                .padding(7).background(Color(red: 0.17, green: 0.16, blue: 0.13), in: RoundedRectangle(cornerRadius: 16))
        }.buttonStyle(PadPressStyle()).accessibilityLabel(button.label)
    }
    private func systemButtons(horizontal: Bool) -> some View {
        let layout = horizontal ? AnyLayout(HStackLayout(spacing: 22)) : AnyLayout(VStackLayout(spacing: 24))
        return layout {
            ForEach([PadButton.start, .select], id: \.self) { button in
                Button { onPress(button) } label: {
                    Text(button.label).font(.system(.headline, design: .monospaced).bold())
                        .foregroundStyle(Retro.accent).frame(minWidth: 90, maxWidth: 160, minHeight: 48)
                        .background(Retro.black, in: RoundedRectangle(cornerRadius: 10))
                        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Retro.rim, lineWidth: 3))
                }.buttonStyle(PadPressStyle())
            }
        }
    }
}

private struct PadPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.opacity(configuration.isPressed ? 0.65 : 1).offset(y: configuration.isPressed ? 3 : 0)
    }
}
