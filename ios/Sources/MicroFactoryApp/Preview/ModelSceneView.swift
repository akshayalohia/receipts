import SceneKit
import SwiftUI
import UIKit

/// SceneKit view of the downloaded USDZ, standing on a light grey plinth.
/// Orbit with a finger (allowsCameraControl); the model turns slowly on its own.
struct ModelSceneView: UIViewRepresentable {
    let fileURL: URL?

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView(frame: .zero)
        view.backgroundColor = Theme.paperUI
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = false
        view.antialiasingMode = .multisampling4X
        view.rendersContinuously = true // keeps the turntable action drawing
        apply(fileURL, to: view, coordinator: context.coordinator)
        return view
    }

    func updateUIView(_ uiView: SCNView, context: Context) {
        if context.coordinator.loadedURL != fileURL {
            apply(fileURL, to: uiView, coordinator: context.coordinator)
        }
    }

    private func apply(_ url: URL?, to view: SCNView, coordinator: Coordinator) {
        coordinator.loadedURL = url
        let built = PlinthScene.make(modelURL: url)
        view.scene = built.scene
        view.pointOfView = built.camera
        view.defaultCameraController.target = built.target
    }

    final class Coordinator {
        var loadedURL: URL?
    }
}

enum PlinthScene {
    struct Built {
        let scene: SCNScene
        let camera: SCNNode
        let target: SCNVector3
    }

    /// Model normalised to 1 scene unit on its longest side, centred, standing on the plinth top (y = 0).
    static func make(modelURL: URL?) -> Built {
        let scene = SCNScene()
        let root = scene.rootNode

        // Plinth
        let plinth = SCNCylinder(radius: 0.85, height: 0.14)
        let plinthMaterial = SCNMaterial()
        plinthMaterial.diffuse.contents = Theme.plinthUI
        plinthMaterial.lightingModel = .lambert
        plinth.materials = [plinthMaterial]
        let plinthNode = SCNNode(geometry: plinth)
        plinthNode.position = SCNVector3(0, -0.07, 0)
        root.addChildNode(plinthNode)

        // Model
        var modelHeight: Float = 0.5
        if let modelURL, let modelScene = try? SCNScene(url: modelURL, options: nil) {
            let holder = SCNNode()
            for child in modelScene.rootNode.childNodes {
                holder.addChildNode(child)
            }
            let (minimum, maximum) = holder.boundingBox
            let sizeX = maximum.x - minimum.x
            let sizeY = maximum.y - minimum.y
            let sizeZ = maximum.z - minimum.z
            let longest = max(sizeX, max(sizeY, sizeZ))
            if longest > 0 {
                let scale = 1.0 / longest
                holder.pivot = SCNMatrix4MakeTranslation((minimum.x + maximum.x) / 2, minimum.y, (minimum.z + maximum.z) / 2)
                holder.scale = SCNVector3(scale, scale, scale)
                modelHeight = sizeY * scale
            }
            let turntable = SCNNode()
            turntable.addChildNode(holder)
            let spin = SCNAction.rotateBy(x: 0, y: CGFloat.pi * 2, z: 0, duration: 24)
            turntable.runAction(SCNAction.repeatForever(spin))
            root.addChildNode(turntable)
        }

        // Light
        let ambient = SCNNode()
        ambient.light = SCNLight()
        ambient.light?.type = .ambient
        ambient.light?.intensity = 450
        root.addChildNode(ambient)

        let key = SCNNode()
        key.light = SCNLight()
        key.light?.type = .directional
        key.light?.intensity = 900
        key.light?.castsShadow = true
        key.light?.shadowMode = .deferred
        key.light?.shadowColor = UIColor(white: 0, alpha: 0.25)
        key.eulerAngles = SCNVector3(-Float.pi / 3, Float.pi / 5, 0)
        root.addChildNode(key)

        // Camera
        let target = SCNVector3(0, modelHeight * 0.45, 0)
        let camera = SCNNode()
        camera.camera = SCNCamera()
        camera.camera?.fieldOfView = 34
        camera.camera?.zNear = 0.01
        camera.position = SCNVector3(0, 0.75 + modelHeight * 0.4, 2.6)
        camera.look(at: target)
        root.addChildNode(camera)

        return Built(scene: scene, camera: camera, target: target)
    }
}
