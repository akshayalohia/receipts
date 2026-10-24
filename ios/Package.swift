// swift-tools-version: 6.0
import PackageDescription
import Foundation

// Build flags (environment variables, read when the manifest is evaluated):
//   MF_WITH_SDKS=1        default. Set 0 to build without ElevenLabs and WhopCheckout.
//   MF_WITH_ELEVENLABS=0  drop only the ElevenLabs SDK (voice falls back to text chat).
//   MF_WITH_WHOP=0        drop only WhopCheckout (Pay opens whop_purchase_url in Safari).
//   MF_CORE_ONLY=1        only MicroFactoryCore + its tests (for `swift test` on Linux or macOS).
let env = ProcessInfo.processInfo.environment

func flag(_ name: String, _ fallback: Bool) -> Bool {
    guard let raw = env[name]?.lowercased() else { return fallback }
    return raw == "1" || raw == "true" || raw == "yes"
}

let coreOnly = flag("MF_CORE_ONLY", false)
let withSDKs = flag("MF_WITH_SDKS", true)
let withElevenLabs = !coreOnly && flag("MF_WITH_ELEVENLABS", withSDKs)
let withWhop = !coreOnly && flag("MF_WITH_WHOP", withSDKs)

var dependencies: [Package.Dependency] = []
var appDependencies: [Target.Dependency] = ["MicroFactoryCore"]

if withElevenLabs {
    // 3.4.0: the version the SDK README installs (startConversation(conversationToken:), updateContext).
    dependencies.append(.package(url: "https://github.com/elevenlabs/elevenlabs-swift-sdk.git", exact: "3.4.0"))
    appDependencies.append(.product(name: "ElevenLabs", package: "elevenlabs-swift-sdk"))
}
if withWhop {
    // Product "WhopCheckout"; the SDK README pins `from: "0.1.0"` (no newer tag named in the docs).
    dependencies.append(.package(url: "https://github.com/whopio/whopsdk-checkout-swift.git", from: "0.1.0"))
    appDependencies.append(.product(name: "WhopCheckout", package: "whopsdk-checkout-swift"))
}

var products: [Product] = []
var targets: [Target] = [
    .target(
        name: "MicroFactoryCore",
        path: "Sources/MicroFactoryCore"
    ),
    .testTarget(
        name: "MicroFactoryCoreTests",
        dependencies: ["MicroFactoryCore"],
        path: "Tests/MicroFactoryCoreTests"
    ),
]

if !coreOnly {
    // xtool expects exactly one library product: the app.
    products.append(.library(name: "MicroFactoryApp", targets: ["MicroFactoryApp"]))
    targets.append(
        .target(
            name: "MicroFactoryApp",
            dependencies: appDependencies,
            path: "Sources/MicroFactoryApp",
            resources: [.copy("Resources/Config.plist")]
        )
    )
}

let package = Package(
    name: "MicroFactory",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: products,
    dependencies: dependencies,
    targets: targets,
    swiftLanguageModes: [.v5]
)
