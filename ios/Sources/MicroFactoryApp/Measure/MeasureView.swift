import ARKit
import SwiftUI
import MicroFactoryCore

/// Screen 3: tap two points in AR, read the distance in mm, "Add" it as a chip.
/// "Type it instead" is always there (and opens straight away on devices without ARKit).
struct MeasureView: View {
    var onAdd: (MeasurementChip) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var distanceMM: Double?
    @State private var pointCount = 0
    @State private var resetToken = 0
    @State private var label = "Length"
    @State private var showManual = false

    private let arSupported = ARWorldTrackingConfiguration.isSupported

    var body: some View {
        ZStack {
            if arSupported {
                ARMeasureView(distanceMM: $distanceMM, pointCount: $pointCount, resetToken: resetToken)
                    .ignoresSafeArea()
            } else {
                Theme.paper.ignoresSafeArea()
            }

            VStack(spacing: 0) {
                topBar
                Spacer()
                if arSupported && pointCount < 2 {
                    Image(systemName: "plus")
                        .font(.system(size: 22, weight: .light))
                        .foregroundStyle(Color.white)
                        .shadow(color: Color.black.opacity(0.5), radius: 2)
                        .accessibilityHidden(true)
                }
                Spacer()
                panel
            }
        }
        .sheet(isPresented: $showManual) {
            ManualMeasureView(initialLabel: label) { chip in
                onAdd(chip)
                showManual = false
                dismiss()
            }
            .presentationDetents([.medium])
        }
        .onAppear {
            if !arSupported {
                showManual = true
            }
        }
    }

    private var topBar: some View {
        HStack {
            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                    .frame(width: 40, height: 40)
                    .background(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).fill(Theme.paper))
            }
            .accessibilityLabel("Close")
            Spacer()
            Text(Copy.measureTitle)
                .font(Theme.sans(17, .semibold))
                .foregroundStyle(Theme.ink)
                .padding(.horizontal, 14)
                .frame(height: 40)
                .background(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).fill(Theme.paper))
            Spacer()
            Button {
                resetToken += 1
                distanceMM = nil
                pointCount = 0
            } label: {
                Image(systemName: "arrow.counterclockwise")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                    .frame(width: 40, height: 40)
                    .background(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).fill(Theme.paper))
            }
            .accessibilityLabel("Start again")
            .opacity(arSupported ? 1 : 0)
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
    }

    private var panel: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let distanceMM {
                Text(Format.mm(distanceMM))
                    .font(Theme.mono(34, .semibold))
                    .foregroundStyle(Theme.ink)
            } else {
                Text(Copy.measureHint)
                    .font(Theme.sans(17, .medium))
                    .foregroundStyle(Theme.ink)
            }
            TextField("Label", text: $label)
                .font(Theme.sans(16))
                .textInputAutocapitalization(.sentences)
                .padding(.horizontal, 12)
                .frame(height: 44)
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                        .stroke(Theme.hairline, lineWidth: 1)
                )
            Button(Copy.measureAdd) {
                guard let distanceMM else { return }
                onAdd(MeasurementChip(label: cleanLabel, mm: (distanceMM * 10).rounded() / 10))
                dismiss()
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(distanceMM == nil)

            Button(Copy.measureTypeIt) {
                showManual = true
            }
            .font(Theme.sans(15, .medium))
            .foregroundStyle(Theme.ink)
            .underline()
            .frame(maxWidth: .infinity)
            .padding(.top, 2)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .fill(Theme.paper)
        )
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
    }

    private var cleanLabel: String {
        let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Length" : trimmed
    }
}

/// Manual entry: label + millimetres.
struct ManualMeasureView: View {
    var initialLabel: String
    var onAdd: (MeasurementChip) -> Void

    @State private var label = ""
    @State private var millimetres = ""
    @FocusState private var valueFocused: Bool

    private var value: Double? {
        let normalised = millimetres.replacingOccurrences(of: ",", with: ".").trimmingCharacters(in: .whitespaces)
        guard let number = Double(normalised), number > 0 else { return nil }
        return number
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(Copy.measureTitle)
                .font(Theme.sans(22, .bold))
                .foregroundStyle(Theme.ink)
            TextField("Label", text: $label)
                .font(Theme.sans(16))
                .padding(.horizontal, 12)
                .frame(height: 44)
                .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).stroke(Theme.hairline, lineWidth: 1))
            HStack(spacing: 8) {
                TextField("0", text: $millimetres)
                    .font(Theme.mono(20, .medium))
                    .keyboardType(.decimalPad)
                    .focused($valueFocused)
                Text("mm")
                    .font(Theme.mono(16))
                    .foregroundStyle(Theme.muted)
            }
            .padding(.horizontal, 12)
            .frame(height: 52)
            .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).stroke(Theme.ink, lineWidth: 1))
            Button(Copy.measureAdd) {
                guard let value else { return }
                let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
                onAdd(MeasurementChip(label: trimmed.isEmpty ? "Length" : trimmed, mm: value))
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(value == nil)
            Spacer(minLength: 0)
        }
        .padding(20)
        .background(Theme.paper.ignoresSafeArea())
        .onAppear {
            label = initialLabel
            valueFocused = true
        }
    }
}
