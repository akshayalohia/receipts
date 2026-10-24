import SwiftUI
import UIKit
import MicroFactoryCore

// MARK: - Buttons

struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(17, .semibold))
            .foregroundStyle(Theme.ink)
            .lineLimit(1)
            .minimumScaleFactor(0.85)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .fill(Theme.accent)
            )
            .opacity(isEnabled ? (configuration.isPressed ? 0.88 : 1) : 0.4)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(16, .semibold))
            .foregroundStyle(Theme.ink)
            .lineLimit(1)
            .minimumScaleFactor(0.85)
            .padding(.horizontal, 10)
            .frame(maxWidth: .infinity, minHeight: 48)
            .background(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .fill(configuration.isPressed ? Theme.hairline.opacity(0.5) : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .stroke(Theme.ink, lineWidth: 1)
            )
            .opacity(isEnabled ? 1 : 0.4)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// Small hairline pill used in the composer (Photos, Measure, Colour).
struct PillLabel: View {
    let title: String
    let systemImage: String
    var swatch: Color? = nil

    var body: some View {
        HStack(spacing: 6) {
            if let swatch {
                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .fill(swatch)
                    .frame(width: 12, height: 12)
                    .overlay(RoundedRectangle(cornerRadius: 3, style: .continuous).stroke(Theme.ink.opacity(0.3), lineWidth: 1))
            } else {
                Image(systemName: systemImage)
                    .font(.system(size: 13, weight: .medium))
            }
            Text(title)
                .font(Theme.sans(14, .medium))
        }
        .foregroundStyle(Theme.ink)
        .padding(.horizontal, 10)
        .frame(height: 32)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .stroke(Theme.hairline, lineWidth: 1)
        )
        .contentShape(Rectangle())
    }
}

// MARK: - Bits

struct Hairline: View {
    var body: some View {
        Rectangle()
            .fill(Theme.hairline)
            .frame(height: 1)
    }
}

/// The "Micro Factory" wordmark: a small orange square and the name.
struct Wordmark: View {
    var body: some View {
        HStack(spacing: 8) {
            Rectangle()
                .fill(Theme.accent)
                .frame(width: 11, height: 11)
            Text(Copy.appName)
                .font(Theme.sans(17, .semibold))
                .foregroundStyle(Theme.ink)
        }
        .accessibilityElement(children: .combine)
    }
}

struct ErrorBanner: View {
    let text: String
    var retry: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Rectangle()
                .fill(Theme.accent)
                .frame(width: 3)
            Text(text)
                .font(Theme.sans(14))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            if let retry {
                Button(action: retry) {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Theme.ink)
                        .frame(width: 32, height: 32)
                }
                .accessibilityLabel("Retry")
            }
        }
        .padding(10)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .stroke(Theme.hairline, lineWidth: 1)
        )
    }
}

/// A measurement chip: label in SF Pro, value in SF Mono.
struct MeasurementChipView: View {
    let chip: MeasurementChip
    var onRemove: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "ruler")
                .font(.system(size: 12))
            Text(chip.label)
                .font(Theme.sans(13, .medium))
            Text(Format.mm(chip.mm))
                .font(Theme.mono(13, .medium))
            if let onRemove {
                Button(action: onRemove) {
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .bold))
                        .frame(width: 20, height: 20)
                }
                .accessibilityLabel("Remove \(chip.label)")
            }
        }
        .foregroundStyle(Theme.ink)
        .padding(.leading, 10)
        .padding(.trailing, onRemove == nil ? 10 : 4)
        .frame(height: 32)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .stroke(Theme.ink, lineWidth: 1)
        )
    }
}

// MARK: - Images from the factory (auth headers needed)

/// Loads an image through `APIClient` (sends X-App-Key / X-Device-Id), on a plinth-grey panel.
struct RemoteImage: View {
    let url: URL?
    let api: APIClient
    var contentMode: ContentMode = .fit

    @State private var image: UIImage?

    var body: some View {
        ZStack {
            Theme.plinthPanel
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            }
        }
        .task(id: url?.absoluteString ?? "") {
            await load()
        }
    }

    private func load() async {
        guard let url else {
            image = nil
            return
        }
        do {
            let data = try await api.data(at: url)
            image = UIImage(data: data)
        } catch {
            // keep the empty panel
        }
    }
}

/// Skeleton block for loading states.
struct SkeletonBlock: View {
    var height: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
            .fill(Theme.hairline.opacity(0.45))
            .frame(maxWidth: .infinity)
            .frame(height: height)
    }
}

extension View {
    /// Paper background and an opaque paper navigation bar.
    func workshopScreen() -> some View {
        self
            .background(Theme.paper.ignoresSafeArea())
            .toolbarBackground(Theme.paper, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
    }
}
