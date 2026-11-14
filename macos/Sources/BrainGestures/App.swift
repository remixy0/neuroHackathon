import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    var hub: Hub?
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { hub?.stopAll() }
}

@main
struct BrainGesturesApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var hub = Hub()

    var body: some Scene {
        WindowGroup("BrainGestures") {
            ContentView()
                .environmentObject(hub)
                .frame(minWidth: 1040, minHeight: 680)
                .onAppear {
                    delegate.hub = hub
                    hub.start()
                }
        }
        .defaultSize(width: 1240, height: 800)
    }
}
