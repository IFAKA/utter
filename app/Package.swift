// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Utter",
    platforms: [.macOS(.v13)],
    targets: [
        .target(name: "TypingCore", resources: [.copy("Resources")]),
        .executableTarget(name: "Utter", dependencies: ["TypingCore"]),
        .executableTarget(name: "st-gate", dependencies: ["TypingCore"]),
    ]
)
