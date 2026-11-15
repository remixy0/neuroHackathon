// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "HaloController",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "HaloCore", targets: ["HaloCore"])],
    targets: [
        .target(name: "HaloCore"),
        .executableTarget(name: "HaloSmoke", dependencies: ["HaloCore"]),
        .executableTarget(name: "HaloDesktopPreview", dependencies: ["HaloCore"], path: "App", exclude: ["Info.plist"]),
        .executableTarget(name: "HaloProtocolChecks", dependencies: ["HaloCore"], path: "Tests/HaloCoreTests")
    ]
)
