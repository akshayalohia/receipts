import SafariServices
import SwiftUI
import UIKit

/// Fallback checkout: opens `whop_purchase_url` in an SFSafariViewController.
struct SafariView: UIViewControllerRepresentable {
    let url: URL
    var onFinish: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onFinish: onFinish)
    }

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let controller = SFSafariViewController(url: url)
        controller.preferredControlTintColor = Theme.inkUI
        controller.dismissButtonStyle = .done
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ uiViewController: SFSafariViewController, context: Context) {}

    final class Coordinator: NSObject, SFSafariViewControllerDelegate {
        let onFinish: () -> Void

        init(onFinish: @escaping () -> Void) {
            self.onFinish = onFinish
        }

        func safariViewControllerDidFinish(_ controller: SFSafariViewController) {
            onFinish()
        }
    }
}

/// `URL` wrapper so it can drive `.sheet(item:)`.
struct IdentifiedURL: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}
