import ARKit
import QuickLook
import UIKit

/// "View on your desk": AR Quick Look of the USDZ at true size (content scaling off).
@MainActor
enum ARQuickLook {
    /// QLPreviewController holds its data source weakly; keep it alive here.
    private static var currentSource: ARQuickLookSource?

    static func present(fileURL: URL) {
        guard let presenter = topViewController() else { return }
        let source = ARQuickLookSource(fileURL: fileURL)
        currentSource = source
        let controller = QLPreviewController()
        controller.dataSource = source
        presenter.present(controller, animated: true)
    }

    private static func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let windows = scenes.flatMap { $0.windows }
        let window: UIWindow? = windows.first(where: { $0.isKeyWindow }) ?? windows.first
        guard let root = window?.rootViewController else {
            return nil
        }
        var top = root
        while let presented = top.presentedViewController {
            top = presented
        }
        return top
    }
}

final class ARQuickLookSource: NSObject, QLPreviewControllerDataSource {
    private let item: ARQuickLookPreviewItem

    init(fileURL: URL) {
        let item = ARQuickLookPreviewItem(fileAt: fileURL)
        item.allowsContentScaling = false
        self.item = item
    }

    func numberOfPreviewItems(in controller: QLPreviewController) -> Int {
        1
    }

    func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem {
        item
    }
}
