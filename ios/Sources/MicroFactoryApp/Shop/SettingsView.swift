import SwiftUI
import MicroFactoryCore

/// Hidden settings (long-press the wordmark): change the server address at runtime.
struct SettingsView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss

    @State private var address = ""
    @State private var note: String?
    @State private var checking = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://factory.example.com", text: $address)
                        .font(Theme.mono(15))
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled(true)
                    Button("Save") {
                        if app.setBaseURL(address) {
                            note = "Saved."
                        } else {
                            note = "Enter a full http:// or https:// address."
                        }
                    }
                    .disabled(address.trimmingCharacters(in: .whitespacesAndNewlines) == app.baseURLString)
                    Button("Use Config.plist value") {
                        app.resetBaseURL()
                        address = app.baseURLString
                        note = nil
                    }
                } header: {
                    Text("Server address")
                } footer: {
                    Text("Config.plist: \(app.config.apiBaseURL)")
                        .font(Theme.mono(12))
                }

                Section {
                    Button {
                        Task { await check() }
                    } label: {
                        HStack {
                            Text("Test connection")
                            Spacer()
                            if checking {
                                ProgressView()
                            }
                        }
                    }
                    .disabled(checking)
                    if let note {
                        Text(note)
                            .font(Theme.sans(14))
                            .foregroundStyle(Theme.ink)
                    }
                }

                Section {
                    Text(app.deviceId)
                        .font(Theme.mono(13))
                        .textSelection(.enabled)
                } header: {
                    Text("Device id")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.paper.ignoresSafeArea())
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .onAppear {
            address = app.baseURLString
        }
    }

    private func check() async {
        checking = true
        defer { checking = false }
        do {
            let health = try await app.api.health()
            var text = health.ok ? "Connected." : "The factory answered but is not ok."
            if let state = health.printerState {
                text += " Printer: \(state)."
            }
            if health.mock {
                text += " Mock mode."
            }
            note = text
        } catch {
            note = userMessage(for: error)
        }
    }
}
