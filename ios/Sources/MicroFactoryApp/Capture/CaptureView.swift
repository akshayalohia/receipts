import PhotosUI
import SwiftUI
import UIKit

/// Screen 2: up to 4 photos from the camera or the library. They upload with the next message.
struct CaptureView: View {
    @Bindable var model: OrderModel
    @Environment(\.dismiss) private var dismiss

    @State private var libraryItems: [PhotosPickerItem] = []
    @State private var showCamera = false
    @State private var isLoading = false

    private let columns = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
    private var remaining: Int { max(0, OrderModel.maxPhotos - model.pendingPhotos.count) }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 20) {
                Text("Up to \(OrderModel.maxPhotos) photos. Fill the frame, with something for scale if you can.")
                    .font(Theme.sans(15))
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)

                LazyVGrid(columns: columns, spacing: 10) {
                    ForEach(0..<OrderModel.maxPhotos, id: \.self) { index in
                        slot(index)
                    }
                }

                HStack(spacing: 10) {
                    Button {
                        showCamera = true
                    } label: {
                        Label("Camera", systemImage: "camera")
                    }
                    .buttonStyle(SecondaryButtonStyle())
                    .disabled(remaining == 0 || !UIImagePickerController.isSourceTypeAvailable(.camera))

                    PhotosPicker(selection: $libraryItems,
                                 maxSelectionCount: max(1, remaining),
                                 matching: .images) {
                        Label("Library", systemImage: "photo.on.rectangle")
                    }
                    .buttonStyle(SecondaryButtonStyle())
                    .disabled(remaining == 0)
                }

                Spacer()

                Button("Done") {
                    dismiss()
                }
                .buttonStyle(PrimaryButtonStyle())
            }
            .padding(20)
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle("Photos")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Theme.paper, for: .navigationBar)
            .overlay {
                if isLoading {
                    ProgressView()
                        .tint(Theme.ink)
                }
            }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { image in
                if let image {
                    model.addPhoto(image)
                }
                showCamera = false
            }
            .ignoresSafeArea()
        }
        .onChange(of: libraryItems) { _, items in
            guard !items.isEmpty else { return }
            Task { await loadLibrary(items) }
        }
    }

    @ViewBuilder
    private func slot(_ index: Int) -> some View {
        let shape = RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
        if index < model.pendingPhotos.count {
            let photo = model.pendingPhotos[index]
            Color.clear
                .aspectRatio(1, contentMode: .fit)
                .overlay(
                    Image(uiImage: photo.thumbnail)
                        .resizable()
                        .scaledToFill()
                )
                .clipShape(shape)
                .overlay(alignment: .topTrailing) {
                    Button {
                        model.removePhoto(photo.id)
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(Theme.paper)
                            .frame(width: 26, height: 26)
                            .background(Circle().fill(Theme.ink))
                    }
                    .padding(6)
                    .accessibilityLabel("Remove photo \(index + 1)")
                }
        } else {
            shape
                .strokeBorder(Theme.hairline, style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
                .aspectRatio(1, contentMode: .fit)
                .overlay(
                    Text("\(index + 1)")
                        .font(Theme.mono(15))
                        .foregroundStyle(Theme.muted)
                )
        }
    }

    private func loadLibrary(_ items: [PhotosPickerItem]) async {
        isLoading = true
        defer {
            isLoading = false
            libraryItems = []
        }
        for item in items {
            guard model.pendingPhotos.count < OrderModel.maxPhotos else { break }
            if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                model.addPhoto(image)
            }
        }
    }
}

/// UIImagePickerController camera, reporting the photo (or nil on cancel).
struct CameraPicker: UIViewControllerRepresentable {
    var onFinish: (UIImage?) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onFinish: onFinish)
    }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.allowsEditing = false
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onFinish: (UIImage?) -> Void

        init(onFinish: @escaping (UIImage?) -> Void) {
            self.onFinish = onFinish
        }

        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onFinish(info[.originalImage] as? UIImage)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            onFinish(nil)
        }
    }
}
