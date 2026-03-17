import SwiftUI

struct LocalSetupView: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var showContent = false
    @State private var glow = false
    @FocusState private var launchFocused: Bool
    @FocusState private var stopRelaunchFocused: Bool

    private var canLaunch: Bool {
        !vm.floors.isEmpty ? !vm.selectedFloors.isEmpty : true
    }

    private let roundOptions = [3, 5, 7, 10]
    private let difficultyOptions = [
        ("easy", "Easy"),
        ("mixed", "Mixed"),
        ("hard", "Hard"),
    ]

    var body: some View {
        VStack(spacing: 36) {
            // Title
            Text("MISSION SETUP")
                .font(.system(size: 24, weight: .bold, design: .monospaced))
                .tracking(8)
                .foregroundColor(mcAccent)
                .padding(.bottom, 8)

            if vm.isLoadingConfig {
                Spacer()
                ProgressView()
                    .scaleEffect(2)
                    .tint(mcAccent)
                Spacer()
            } else {
                // Theme selection
                if !vm.themes.isEmpty {
                    SectionRow(label: "THEME") {
                        ForEach(vm.themes) { theme in
                            PillButton(
                                title: theme.name,
                                isSelected: vm.selectedTheme == theme.id
                            ) {
                                vm.selectedTheme = theme.id
                            }
                        }
                    }
                    .focusSection()
                    .opacity(showContent ? 1 : 0)
                    .offset(y: showContent ? 0 : 15)
                }

                // Difficulty
                SectionRow(label: "DIFFICULTY") {
                    ForEach(difficultyOptions, id: \.0) { (value, label) in
                        PillButton(
                            title: label,
                            isSelected: vm.selectedDifficulty == value
                        ) {
                            vm.selectedDifficulty = value
                        }
                    }
                }
                .focusSection()
                .opacity(showContent ? 1 : 0)
                .offset(y: showContent ? 0 : 15)
                .animation(.easeOut(duration: 0.4).delay(0.05), value: showContent)

                // Rounds
                SectionRow(label: "ROUNDS") {
                    ForEach(roundOptions, id: \.self) { count in
                        PillButton(
                            title: "\(count)",
                            isSelected: vm.selectedRounds == count
                        ) {
                            vm.selectedRounds = count
                        }
                    }
                }
                .focusSection()
                .opacity(showContent ? 1 : 0)
                .offset(y: showContent ? 0 : 15)
                .animation(.easeOut(duration: 0.4).delay(0.1), value: showContent)

                // Floors (optional)
                if !vm.floors.isEmpty {
                    SectionRow(label: "FLOORS") {
                        ForEach(vm.floors) { floor in
                            PillButton(
                                title: floor.name,
                                isSelected: vm.selectedFloors.contains(floor.id)
                            ) {
                                if vm.selectedFloors.contains(floor.id) {
                                    vm.selectedFloors.remove(floor.id)
                                } else {
                                    vm.selectedFloors.insert(floor.id)
                                }
                            }
                        }
                    }
                    .focusSection()
                    .opacity(showContent ? 1 : 0)
                    .offset(y: showContent ? 0 : 15)
                    .animation(.easeOut(duration: 0.4).delay(0.15), value: showContent)
                }

                // Launch button
                Button(action: { vm.startLocalGame() }) {
                    HStack(spacing: 12) {
                        Image(systemName: "paperplane.fill")
                        Text("LAUNCH MISSION")
                            .font(.system(size: 24, weight: .bold, design: .monospaced))
                            .tracking(4)
                    }
                    .padding(.horizontal, 56)
                    .padding(.vertical, 20)
                    .background(
                        LinearGradient(colors: canLaunch
                            ? (launchFocused
                                ? [mcSuccess, mcSuccess.opacity(0.8)]
                                : [mcSuccess.opacity(0.3), mcSuccess.opacity(0.2)])
                            : [Color.gray.opacity(0.3), Color.gray.opacity(0.2)],
                                       startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 18)
                            .stroke(canLaunch ? mcSuccess.opacity(launchFocused ? 0.6 : 0.3) : Color.clear, lineWidth: launchFocused ? 2 : 1)
                    )
                    .foregroundColor(canLaunch ? (launchFocused ? .white : mcSuccess) : .gray)
                    .cornerRadius(18)
                    .scaleEffect(launchFocused ? 1.05 : 1.0)
                    .animation(.easeInOut(duration: 0.15), value: launchFocused)
                }
                .buttonStyle(.mc)
                .focused($launchFocused)
                .disabled(!canLaunch)
                .shadow(color: canLaunch ? mcSuccess.opacity(launchFocused ? (glow ? 0.5 : 0.3) : 0.1) : .clear, radius: launchFocused ? (glow ? 24 : 12) : 6, y: 4)
                .opacity(showContent ? 1 : 0)
                .animation(.easeOut(duration: 0.4).delay(0.2), value: showContent)
                .padding(.top, 16)

                // Game already running conflict
                if vm.gameAlreadyRunning {
                    VStack(spacing: 16) {
                        Text("A game is already in progress")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundColor(mcWarning)

                        Button(action: { vm.stopAndRelaunch() }) {
                            HStack(spacing: 10) {
                                Image(systemName: "arrow.counterclockwise")
                                Text("STOP & RELAUNCH")
                                    .font(.system(size: 20, weight: .bold, design: .monospaced))
                                    .tracking(2)
                            }
                            .padding(.horizontal, 40)
                            .padding(.vertical, 16)
                            .background(stopRelaunchFocused ? mcWarning : mcWarning.opacity(0.15))
                            .foregroundColor(stopRelaunchFocused ? mcBg : mcWarning)
                            .overlay(
                                RoundedRectangle(cornerRadius: 14)
                                    .stroke(mcWarning.opacity(stopRelaunchFocused ? 0.8 : 0.4), lineWidth: stopRelaunchFocused ? 2 : 1)
                            )
                            .cornerRadius(14)
                            .scaleEffect(stopRelaunchFocused ? 1.05 : 1.0)
                            .shadow(color: stopRelaunchFocused ? mcWarning.opacity(0.3) : .clear, radius: 8)
                            .animation(.easeInOut(duration: 0.15), value: stopRelaunchFocused)
                        }
                        .buttonStyle(.mc)
                        .focused($stopRelaunchFocused)
                    }
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
        }
        .padding(60)
        .onExitCommand {
            vm.appMode = .home
        }
        .onAppear {
            Task {
                await vm.fetchThemesAndFloors()
            }
            withAnimation(.easeOut(duration: 0.4)) {
                showContent = true
            }
            withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                glow = true
            }
        }
    }
}

// MARK: - Section Row

struct SectionRow<Content: View>: View {
    let label: String
    var hint: String? = nil
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Text(label)
                    .font(.system(size: 16, weight: .bold, design: .monospaced))
                    .tracking(4)
                    .foregroundColor(.gray)

                if let hint = hint {
                    Text(hint)
                        .font(.caption)
                        .foregroundColor(.gray.opacity(0.5))
                }
            }

            HStack(spacing: 16) {
                content()
            }
        }
    }
}

// MARK: - Pill Button

struct PillButton: View {
    let title: String
    let isSelected: Bool
    let action: () -> Void
    @FocusState private var isFocused: Bool

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 20, weight: isSelected ? .bold : .medium))
                .padding(.horizontal, 28)
                .padding(.vertical, 12)
                .background(
                    Capsule()
                        .fill(isSelected ? mcAccent : (isFocused ? Color.white.opacity(0.15) : mcCard))
                )
                .foregroundColor(isSelected ? mcBg : .white)
                .overlay(
                    Capsule()
                        .stroke(isFocused && !isSelected ? mcAccent.opacity(0.6) : (isSelected ? mcAccent : Color.white.opacity(0.15)), lineWidth: isFocused ? 2 : 1)
                )
                .clipShape(Capsule())
                .shadow(color: isFocused ? mcAccent.opacity(0.3) : .clear, radius: 8)
                .scaleEffect(isFocused ? 1.05 : 1.0)
                .animation(.easeInOut(duration: 0.15), value: isFocused)
        }
        .buttonStyle(.mc)
        .focused($isFocused)
    }
}
