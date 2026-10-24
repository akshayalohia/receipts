import ARKit
import RealityKit
import SwiftUI
import UIKit

/// RealityKit ARView: tap two points, raycast to estimated planes, report the distance in mm.
struct ARMeasureView: UIViewRepresentable {
    @Binding var distanceMM: Double?
    @Binding var pointCount: Int
    var resetToken: Int

    func makeCoordinator() -> Coordinator {
        Coordinator(distanceMM: $distanceMM, pointCount: $pointCount)
    }

    func makeUIView(context: Context) -> ARView {
        let view = ARView(frame: .zero, cameraMode: .ar, automaticallyConfigureSession: false)
        let configuration = ARWorldTrackingConfiguration()
        configuration.planeDetection = [.horizontal, .vertical]
        view.session.run(configuration)
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.handleTap(_:)))
        view.addGestureRecognizer(tap)
        context.coordinator.arView = view
        context.coordinator.lastResetToken = resetToken
        return view
    }

    func updateUIView(_ uiView: ARView, context: Context) {
        context.coordinator.distanceMM = $distanceMM
        context.coordinator.pointCount = $pointCount
        if context.coordinator.lastResetToken != resetToken {
            context.coordinator.lastResetToken = resetToken
            context.coordinator.clear()
        }
    }

    static func dismantleUIView(_ uiView: ARView, coordinator: Coordinator) {
        uiView.session.pause()
    }

    @MainActor
    final class Coordinator: NSObject {
        var distanceMM: Binding<Double?>
        var pointCount: Binding<Int>
        weak var arView: ARView?
        var lastResetToken = 0

        private var points: [SIMD3<Float>] = []
        private var anchors: [AnchorEntity] = []

        init(distanceMM: Binding<Double?>, pointCount: Binding<Int>) {
            self.distanceMM = distanceMM
            self.pointCount = pointCount
        }

        @objc func handleTap(_ recognizer: UITapGestureRecognizer) {
            guard let view = arView else { return }
            let location = recognizer.location(in: view)
            let results = view.raycast(from: location, allowing: .estimatedPlane, alignment: .any)
            guard let hit = results.first else { return }
            let column = hit.worldTransform.columns.3
            let point = SIMD3<Float>(column.x, column.y, column.z)

            if points.count >= 2 {
                clear()
            }
            points.append(point)
            addMarker(at: point, in: view)

            if points.count == 2 {
                let a = points[0]
                let b = points[1]
                addLine(from: a, to: b, in: view)
                distanceMM.wrappedValue = Double(simd_distance(a, b)) * 1000
            } else {
                distanceMM.wrappedValue = nil
            }
            pointCount.wrappedValue = points.count
        }

        func clear() {
            if let view = arView {
                for anchor in anchors {
                    view.scene.removeAnchor(anchor)
                }
            }
            anchors.removeAll()
            points.removeAll()
            distanceMM.wrappedValue = nil
            pointCount.wrappedValue = 0
        }

        private func addMarker(at point: SIMD3<Float>, in view: ARView) {
            let material = SimpleMaterial(color: Theme.accentUI, isMetallic: false)
            let sphere = ModelEntity(mesh: .generateSphere(radius: 0.004), materials: [material])
            let anchor = AnchorEntity(world: point)
            anchor.addChild(sphere)
            view.scene.addAnchor(anchor)
            anchors.append(anchor)
        }

        private func addLine(from a: SIMD3<Float>, to b: SIMD3<Float>, in view: ARView) {
            let length = simd_distance(a, b)
            guard length > 0 else { return }
            let material = SimpleMaterial(color: Theme.accentUI, isMetallic: false)
            let box = ModelEntity(mesh: .generateBox(width: 0.0015, height: 0.0015, depth: length), materials: [material])
            let anchor = AnchorEntity(world: (a + b) / 2)
            box.orientation = simd_quatf(from: SIMD3<Float>(0, 0, 1), to: simd_normalize(b - a))
            anchor.addChild(box)
            view.scene.addAnchor(anchor)
            anchors.append(anchor)
        }
    }
}
