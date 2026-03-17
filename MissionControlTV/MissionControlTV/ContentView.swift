import SwiftUI

// MARK: - Color Constants

let mcAccent = Color(red: 0.22, green: 0.74, blue: 0.97)
let mcSuccess = Color(red: 0.20, green: 0.83, blue: 0.60)
let mcWarning = Color(red: 0.98, green: 0.75, blue: 0.15)
let mcDanger = Color(red: 0.97, green: 0.44, blue: 0.44)
let mcBg = Color(red: 0.031, green: 0.051, blue: 0.102)
let mcCard = Color(red: 0.075, green: 0.110, blue: 0.180)

// MARK: - Content View (Router)

struct ContentView: View {
    @EnvironmentObject var vm: GameViewModel

    var body: some View {
        ZStack {
            // Atmospheric background
            mcBg.ignoresSafeArea()

            RadialGradient(
                colors: [mcAccent.opacity(0.06), .clear],
                center: .top,
                startRadius: 100,
                endRadius: 800
            )
            .ignoresSafeArea()

            switch vm.appMode {
            case .unconfigured:
                FirstTimeSetupView()
                    .transition(.opacity.combined(with: .scale(scale: 0.96)))
            case .home:
                HomeView()
                    .transition(.opacity)
                    .sheet(isPresented: $vm.showSettings) {
                        SettingsView()
                            .environmentObject(vm)
                    }
            case .localSetup:
                LocalSetupView()
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .trailing)),
                        removal: .opacity.combined(with: .move(edge: .trailing))
                    ))
            case .playing:
                GamePlayView()
                    .transition(.opacity)
            }
        }
        .preferredColorScheme(.dark)
        .animation(.easeInOut(duration: 0.4), value: vm.appMode)
    }
}

// MARK: - First Time Setup

struct FirstTimeSetupView: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var showContent = false
    @State private var addressInput = ""
    @State private var isTesting = false
    @State private var testError: String? = nil
    @FocusState private var connectFocused: Bool

    var body: some View {
        VStack(spacing: 36) {
            VStack(spacing: 12) {
                Text("MISSION")
                    .font(.system(size: 28, weight: .bold, design: .monospaced))
                    .tracking(16)
                    .foregroundColor(mcAccent.opacity(0.5))
                    .opacity(showContent ? 1 : 0)
                    .offset(y: showContent ? 0 : -10)

                Text("Control")
                    .font(.system(size: 84, weight: .heavy))
                    .foregroundColor(.white)
                    .shadow(color: mcAccent.opacity(0.3), radius: 30, y: 4)
                    .opacity(showContent ? 1 : 0)
                    .scaleEffect(showContent ? 1 : 0.9)
            }

            Text("FIRST TIME SETUP")
                .font(.system(size: 18, weight: .bold, design: .monospaced))
                .tracking(6)
                .foregroundColor(.gray)
                .opacity(showContent ? 1 : 0)

            VStack(spacing: 16) {
                TextField("Server address (e.g. 192.168.1.100:8765)", text: $addressInput)
                    .textFieldStyle(.plain)
                    .font(.system(.title3, design: .monospaced))
                    .padding()
                    .background(mcCard)
                    .overlay(
                        RoundedRectangle(cornerRadius: 14)
                            .stroke(Color.white.opacity(0.08), lineWidth: 1)
                    )
                    .cornerRadius(14)
                    .frame(maxWidth: 600)

                if let error = testError {
                    Text(error)
                        .font(.callout)
                        .foregroundColor(mcDanger)
                }
            }
            .opacity(showContent ? 1 : 0)
            .offset(y: showContent ? 0 : 20)

            Button {
                Task { await testAndSave() }
            } label: {
                HStack(spacing: 12) {
                    if isTesting {
                        ProgressView()
                            .tint(mcBg)
                    }
                    Text(isTesting ? "Connecting..." : "Connect")
                }
                .font(.title3.weight(.bold))
                .padding(.horizontal, 56)
                .padding(.vertical, 16)
                .background(
                    LinearGradient(colors: connectFocused
                        ? [mcAccent, mcAccent.opacity(0.8)]
                        : [mcAccent.opacity(0.3), mcAccent.opacity(0.2)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing)
                )
                .foregroundColor(connectFocused ? mcBg : mcAccent)
                .cornerRadius(14)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(mcAccent.opacity(connectFocused ? 0.6 : 0.3), lineWidth: connectFocused ? 2 : 1)
                )
                .shadow(color: mcAccent.opacity(connectFocused ? 0.4 : 0.1), radius: connectFocused ? 16 : 6, y: 4)
                .scaleEffect(connectFocused ? 1.05 : 1.0)
                .animation(.easeInOut(duration: 0.15), value: connectFocused)
            }
            .buttonStyle(.mc)
            .focused($connectFocused)
            .opacity(showContent ? 1 : 0)
            .offset(y: showContent ? 0 : 20)
            .disabled(isTesting || addressInput.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .onAppear {
            addressInput = vm.serverAddress
            withAnimation(.easeOut(duration: 0.8)) {
                showContent = true
            }
        }
    }

    private func testAndSave() async {
        isTesting = true
        testError = nil
        vm.serverAddress = addressInput
        vm.saveServerAddress(addressInput)

        let ok = await vm.testConnection()
        if ok {
            // Already saved — stay on home
        } else {
            testError = "Could not reach server. Check the address and try again."
            vm.appMode = .unconfigured
        }
        isTesting = false
    }
}

// MARK: - Settings View

struct SettingsView: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var addressInput = ""
    @State private var isTesting = false
    @State private var connectionStatus: String? = nil
    @State private var connectionOk = false
    @Environment(\.dismiss) var dismiss
    @FocusState private var testFocused: Bool
    @FocusState private var saveFocused: Bool

    var body: some View {
        ZStack {
            mcBg.ignoresSafeArea()

            VStack(spacing: 32) {
                Text("SETTINGS")
                    .font(.system(size: 24, weight: .bold, design: .monospaced))
                    .tracking(8)
                    .foregroundColor(mcAccent)

                VStack(alignment: .leading, spacing: 12) {
                    Text("Server Address")
                        .font(.headline)
                        .foregroundColor(.gray)

                    TextField("e.g. 192.168.1.100:8765", text: $addressInput)
                        .textFieldStyle(.plain)
                        .font(.system(.title3, design: .monospaced))
                        .padding()
                        .background(mcCard)
                        .overlay(
                            RoundedRectangle(cornerRadius: 14)
                                .stroke(Color.white.opacity(0.08), lineWidth: 1)
                        )
                        .cornerRadius(14)
                        .frame(maxWidth: 600)
                }

                if let status = connectionStatus {
                    Text(status)
                        .font(.callout.weight(.semibold))
                        .foregroundColor(connectionOk ? mcSuccess : mcDanger)
                }

                HStack(spacing: 20) {
                    Button {
                        Task { await testConnection() }
                    } label: {
                        HStack(spacing: 8) {
                            if isTesting {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text("Test Connection")
                        }
                        .font(.title3.weight(.semibold))
                        .padding(.horizontal, 32)
                        .padding(.vertical, 14)
                        .background(testFocused ? mcAccent.opacity(0.15) : mcCard)
                        .overlay(
                            RoundedRectangle(cornerRadius: 14)
                                .stroke(testFocused ? mcAccent.opacity(0.5) : Color.white.opacity(0.1), lineWidth: testFocused ? 2 : 1)
                        )
                        .foregroundColor(.white)
                        .cornerRadius(14)
                        .scaleEffect(testFocused ? 1.05 : 1.0)
                        .shadow(color: testFocused ? mcAccent.opacity(0.3) : .clear, radius: 8)
                        .animation(.easeInOut(duration: 0.15), value: testFocused)
                    }
                    .buttonStyle(.mc)
                    .focused($testFocused)
                    .disabled(isTesting)

                    Button {
                        vm.saveServerAddress(addressInput)
                        dismiss()
                    } label: {
                        Text("Save")
                            .font(.title3.weight(.bold))
                            .padding(.horizontal, 48)
                            .padding(.vertical, 14)
                            .background(
                                LinearGradient(colors: saveFocused
                                    ? [mcAccent, mcAccent.opacity(0.8)]
                                    : [mcAccent.opacity(0.3), mcAccent.opacity(0.2)],
                                               startPoint: .topLeading, endPoint: .bottomTrailing)
                            )
                            .foregroundColor(saveFocused ? mcBg : mcAccent)
                            .cornerRadius(14)
                            .overlay(
                                RoundedRectangle(cornerRadius: 14)
                                    .stroke(mcAccent.opacity(saveFocused ? 0.6 : 0.3), lineWidth: saveFocused ? 2 : 1)
                            )
                            .scaleEffect(saveFocused ? 1.05 : 1.0)
                            .shadow(color: saveFocused ? mcAccent.opacity(0.3) : .clear, radius: 8)
                            .animation(.easeInOut(duration: 0.15), value: saveFocused)
                    }
                    .buttonStyle(.mc)
                    .focused($saveFocused)
                }
            }
            .padding(60)
        }
        .onAppear {
            addressInput = vm.serverAddress
        }
    }

    private func testConnection() async {
        isTesting = true
        connectionStatus = nil

        // Temporarily set for testing
        let original = vm.serverAddress
        vm.serverAddress = addressInput

        let ok = await vm.testConnection()
        connectionOk = ok
        connectionStatus = ok ? "Connected successfully!" : "Could not reach server"
        vm.serverAddress = original

        isTesting = false
    }
}

// MARK: - Game Play View (extracted existing game screens)

struct GamePlayView: View {
    @EnvironmentObject var vm: GameViewModel

    private var currentImageURL: String? {
        switch vm.screen {
        case .results, .finale: return vm.outroImageURL
        case .waitingAdvance: return vm.transitionImageURL
        default: return vm.sceneImageURL
        }
    }

    var body: some View {
        ZStack {
            // 1. Theme gradient (always present)
            vm.themeVisuals.backgroundGradient
                .ignoresSafeArea()

            // 2. Scene image if available (light blur, Ken Burns)
            RemoteImageView(
                url: currentImageURL,
                blurRadius: 6,
                opacity: 0.55,
                kenBurnsDuration: 20
            )
            .ignoresSafeArea()

            // 3. Dark vignette overlay for text readability
            VignetteOverlay(intensity: 0.4)

            // 4. Particle system (theme-configured)
            ParticleView(config: vm.themeVisuals.particleConfig)
                .ignoresSafeArea()
                .opacity(0.4)

            // 5. Intro sequence overlay
            if vm.showIntroSequence {
                IntroSequenceView()
                    .transition(.dramatic)
            }

            // 6. Active screen content
            if !vm.showIntroSequence {
                switch vm.screen {
                case .waiting(let message):
                    WaitingView(message: message)
                        .transition(.cinematic)
                case .mission(let info):
                    MissionCardView(mission: info)
                        .transition(.cinematic)
                case .timer(let info, let elapsed):
                    TimerView(mission: info, elapsed: elapsed)
                        .transition(.opacity)
                case .roundComplete(let name, let time):
                    RoundCompleteView(name: name, time: time)
                        .transition(.dramatic)
                case .waitingAdvance:
                    WaitingAdvanceView()
                        .transition(.slideBlur)
                case .finale(let completed, let totalRounds):
                    FinaleView(completed: completed, totalRounds: totalRounds)
                        .transition(.dramatic)
                case .results(let results):
                    ResultsView(results: results)
                        .transition(.cinematic)
                }
            }
        }
        .animation(.easeInOut(duration: 0.5), value: vm.screenId)
        .animation(.easeInOut(duration: 0.8), value: vm.showIntroSequence)
    }
}

// MARK: - Waiting

struct WaitingView: View {
    let message: String
    @EnvironmentObject var vm: GameViewModel
    @State private var ripple1 = false
    @State private var ripple2 = false
    @State private var ripple3 = false
    @FocusState private var backFocused: Bool

    private var isPreGameWait: Bool {
        message.contains("Waiting for game") || message.contains("Error:")
    }

    var body: some View {
        VStack(spacing: 32) {
            ZStack {
                // Concentric ripple rings
                Circle()
                    .stroke(vm.themeVisuals.primary.opacity(0.2), lineWidth: 2)
                    .frame(width: 80, height: 80)
                    .scaleEffect(ripple1 ? 2.0 : 0.8)
                    .opacity(ripple1 ? 0 : 0.6)

                Circle()
                    .stroke(vm.themeVisuals.primary.opacity(0.15), lineWidth: 2)
                    .frame(width: 80, height: 80)
                    .scaleEffect(ripple2 ? 2.0 : 0.8)
                    .opacity(ripple2 ? 0 : 0.5)

                Circle()
                    .stroke(vm.themeVisuals.primary.opacity(0.1), lineWidth: 2)
                    .frame(width: 80, height: 80)
                    .scaleEffect(ripple3 ? 2.0 : 0.8)
                    .opacity(ripple3 ? 0 : 0.4)

                // Ambient glow
                Circle()
                    .fill(vm.themeVisuals.glow.opacity(0.08))
                    .frame(width: 60, height: 60)

                ProgressView()
                    .scaleEffect(2)
                    .tint(vm.themeVisuals.primary)
            }

            Text(message)
                .font(.title2)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)

            if isPreGameWait {
                Button(action: { vm.returnToHome() }) {
                    HStack(spacing: 8) {
                        Image(systemName: "chevron.left")
                        Text("Go Back")
                    }
                    .font(.system(size: 20, weight: .semibold))
                    .padding(.horizontal, 32)
                    .padding(.vertical, 14)
                    .background(backFocused ? mcCard : Color.white.opacity(0.05))
                    .foregroundColor(backFocused ? .white : .gray.opacity(0.6))
                    .overlay(
                        RoundedRectangle(cornerRadius: 14)
                            .stroke(backFocused ? mcAccent.opacity(0.4) : Color.white.opacity(0.08), lineWidth: backFocused ? 2 : 1)
                    )
                    .cornerRadius(14)
                    .scaleEffect(backFocused ? 1.05 : 1.0)
                    .shadow(color: backFocused ? mcAccent.opacity(0.2) : .clear, radius: 8)
                    .animation(.easeInOut(duration: 0.15), value: backFocused)
                }
                .buttonStyle(.mc)
                .focused($backFocused)
                .padding(.top, 8)
            }
        }
        .onAppear {
            withAnimation(.easeOut(duration: 2.0).repeatForever(autoreverses: false)) {
                ripple1 = true
            }
            withAnimation(.easeOut(duration: 2.0).repeatForever(autoreverses: false).delay(0.6)) {
                ripple2 = true
            }
            withAnimation(.easeOut(duration: 2.0).repeatForever(autoreverses: false).delay(1.2)) {
                ripple3 = true
            }
        }
    }
}

// MARK: - Mission Card

struct MissionCardView: View {
    let mission: MissionInfo
    @EnvironmentObject var vm: GameViewModel
    @State private var showRound = false
    @State private var showName = false
    @State private var showRoom = false
    @State private var showBadge = false
    @State private var glowPulse = false

    var body: some View {
        VStack(spacing: 28) {
            Text("ROUND \(mission.round) OF \(mission.totalRounds)")
                .font(.system(size: 18, weight: .bold, design: .monospaced))
                .tracking(4)
                .foregroundColor(vm.themeVisuals.primary.opacity(0.6))
                .opacity(showRound ? 1 : 0)
                .offset(y: showRound ? 0 : -8)

            ZStack {
                // Glow pulse behind mission name
                Text(mission.name)
                    .font(.system(size: 76, weight: .heavy))
                    .foregroundColor(vm.themeVisuals.glow.opacity(glowPulse ? 0.15 : 0.05))
                    .blur(radius: 30)
                    .multilineTextAlignment(.center)

                Text(mission.name)
                    .font(.system(size: 76, weight: .heavy))
                    .foregroundColor(.white)
                    .multilineTextAlignment(.center)
                    .shadow(color: vm.themeVisuals.glow.opacity(0.3), radius: 20, y: 4)
            }
            .opacity(showName ? 1 : 0)
            .scaleEffect(showName ? 1 : 0.85)

            Text(mission.room)
                .font(.system(size: 36, weight: .medium))
                .foregroundColor(.gray)
                .opacity(showRoom ? 1 : 0)
                .offset(y: showRoom ? 0 : 12)

            DifficultyBadge(difficulty: mission.difficulty)
                .opacity(showBadge ? 1 : 0)
                .scaleEffect(showBadge ? 1 : 0.7)
        }
        .textBackdrop()
        .padding(60)
        .onAppear {
            // Staggered entrance
            withAnimation(.easeOut(duration: 0.4)) {
                showRound = true
            }
            withAnimation(.spring(response: 0.5, dampingFraction: 0.7).delay(0.15)) {
                showName = true
            }
            withAnimation(.easeOut(duration: 0.4).delay(0.35)) {
                showRoom = true
            }
            withAnimation(.spring(response: 0.4, dampingFraction: 0.6).delay(0.5)) {
                showBadge = true
            }
            withAnimation(.easeInOut(duration: 2.0).repeatForever(autoreverses: true).delay(0.6)) {
                glowPulse = true
            }
        }
    }
}

// MARK: - Timer

struct TimerView: View {
    let mission: MissionInfo
    let elapsed: Double
    @EnvironmentObject var vm: GameViewModel
    @State private var vignettePulse = false

    private var timerColor: Color {
        if elapsed > 35 { return mcDanger }
        if elapsed > 25 { return mcWarning }
        return vm.themeVisuals.primary
    }

    private var glowOpacity: Double {
        if elapsed > 35 { return 0.5 }
        if elapsed > 25 { return 0.35 }
        return 0.2
    }

    private var glowRadius: CGFloat {
        if elapsed > 35 { return 60 }
        if elapsed > 25 { return 50 }
        return 40
    }

    var body: some View {
        ZStack {
            // Red vignette at high urgency
            if elapsed > 35 {
                RadialGradient(
                    colors: [.clear, mcDanger.opacity(vignettePulse ? 0.25 : 0.10)],
                    center: .center,
                    startRadius: 400,
                    endRadius: 900
                )
                .ignoresSafeArea()
                .allowsHitTesting(false)
                .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: vignettePulse)
                .onAppear { vignettePulse = true }
            }

            VStack(spacing: 16) {
                Text("ROUND \(mission.round) OF \(mission.totalRounds)")
                    .font(.system(size: 16, weight: .bold, design: .monospaced))
                    .tracking(3)
                    .foregroundColor(.gray.opacity(0.6))

                Text(mission.name)
                    .font(.system(size: 44, weight: .bold))
                    .foregroundColor(.white)

                Text(mission.room)
                    .font(.title3)
                    .foregroundColor(.gray)

                Text(String(format: "%.1f", elapsed))
                    .font(.system(size: 160, weight: .heavy, design: .monospaced))
                    .foregroundColor(timerColor)
                    .shadow(color: timerColor.opacity(glowOpacity), radius: glowRadius, y: 0)
                    .padding(.vertical, 12)
                    .contentTransition(.numericText())
                    .animation(.linear(duration: 0.1), value: elapsed)

                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule()
                            .fill(Color.white.opacity(0.06))
                            .frame(height: 8)

                        ZStack(alignment: .trailing) {
                            Capsule()
                                .fill(timerColor)
                                .frame(width: geo.size.width * min(elapsed / 45.0, 1.0), height: 8)

                            // Glowing leading edge
                            Circle()
                                .fill(timerColor)
                                .frame(width: 14, height: 14)
                                .shadow(color: timerColor.opacity(0.8), radius: elapsed > 25 ? 12 : 6)
                                .offset(x: 3)
                        }
                        .frame(width: geo.size.width * min(elapsed / 45.0, 1.0), alignment: .leading)
                    }
                }
                .frame(maxWidth: 600, maxHeight: 14)

                GameControlButtons()
                    .padding(.top, 20)
            }
            .textBackdrop(padding: 40)
            .padding(60)
        }
    }
}

// MARK: - Round Complete

struct RoundCompleteView: View {
    let name: String
    let time: Double
    @EnvironmentObject var vm: GameViewModel
    @State private var showCheck = false
    @State private var showText = false
    @State private var showParticles = false

    var body: some View {
        ZStack {
            // Firework particles on success
            if showParticles {
                CelebrationParticles(colors: [
                    mcSuccess,
                    vm.themeVisuals.primary,
                    vm.themeVisuals.glow,
                    .white
                ])
                .ignoresSafeArea()
            }

            VStack(spacing: 28) {
                ZStack {
                    Circle()
                        .fill(mcSuccess.opacity(0.1))
                        .frame(width: 140, height: 140)
                        .scaleEffect(showCheck ? 1 : 0.5)
                        .opacity(showCheck ? 1 : 0)

                    // Glow ring
                    Circle()
                        .stroke(mcSuccess.opacity(0.3), lineWidth: 3)
                        .frame(width: 160, height: 160)
                        .scaleEffect(showCheck ? 1.2 : 0.5)
                        .opacity(showCheck ? 0 : 0.8)

                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 100))
                        .foregroundColor(mcSuccess)
                        .shadow(color: mcSuccess.opacity(0.4), radius: 20)
                        .scaleEffect(showCheck ? 1 : 0)
                        .rotationEffect(.degrees(showCheck ? 0 : -30))
                }

                Text("Mission Complete!")
                    .font(.system(size: 52, weight: .heavy))
                    .foregroundColor(.white)
                    .shadow(color: vm.themeVisuals.glow.opacity(0.2), radius: 16)
                    .opacity(showText ? 1 : 0)
                    .offset(y: showText ? 0 : 15)

                Text(name)
                    .font(.title2)
                    .foregroundColor(.gray)
                    .opacity(showText ? 1 : 0)

                Text(String(format: "%.1fs", time))
                    .font(.system(size: 68, weight: .heavy, design: .monospaced))
                    .foregroundColor(vm.themeVisuals.primary)
                    .shadow(color: vm.themeVisuals.primary.opacity(0.3), radius: 20)
                    .opacity(showText ? 1 : 0)
                    .scaleEffect(showText ? 1 : 0.8)
            }
            .textBackdrop()
        }
        .onAppear {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.6)) {
                showCheck = true
            }
            withAnimation(.easeOut(duration: 0.5).delay(0.3)) {
                showText = true
            }
            showParticles = true
        }
    }
}

// MARK: - Waiting for Advance

struct WaitingAdvanceView: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var glow = false
    @FocusState private var nextFocused: Bool

    var body: some View {
        VStack(spacing: 40) {
            Text("Head back to\nMission Control!")
                .font(.system(size: 52, weight: .heavy))
                .foregroundColor(.white)
                .multilineTextAlignment(.center)
                .shadow(color: vm.themeVisuals.glow.opacity(0.15), radius: 16)

            Text("Press to continue")
                .font(.title2)
                .foregroundColor(.gray)

            Button(action: { vm.advance() }) {
                Text("Next Mission")
                    .font(.system(size: 34, weight: .bold))
                    .padding(.horizontal, 72)
                    .padding(.vertical, 22)
                    .background(
                        LinearGradient(colors: nextFocused
                            ? [mcSuccess, mcSuccess.opacity(0.8)]
                            : [mcSuccess.opacity(0.3), mcSuccess.opacity(0.2)],
                                       startPoint: .topLeading, endPoint: .bottomTrailing)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 18)
                            .stroke(mcSuccess.opacity(nextFocused ? 0.6 : 0.3), lineWidth: nextFocused ? 2 : 1)
                    )
                    .foregroundColor(nextFocused ? .white : mcSuccess)
                    .cornerRadius(18)
                    .shadow(color: mcSuccess.opacity(nextFocused ? (glow ? 0.5 : 0.3) : 0.1), radius: nextFocused ? (glow ? 24 : 12) : 6, y: 4)
                    .scaleEffect(nextFocused ? (glow ? 1.05 : 1.03) : 1)
                    .animation(.easeInOut(duration: 0.15), value: nextFocused)
            }
            .buttonStyle(.mc)
            .focused($nextFocused)
            .onAppear {
                withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                    glow = true
                }
            }

            GameControlButtons()
        }
        .textBackdrop()
    }
}

// MARK: - Finale (shown during outro TTS)

struct FinaleView: View {
    let completed: Int
    let totalRounds: Int
    @EnvironmentObject var vm: GameViewModel
    @State private var showTitle = false
    @State private var showStats = false
    @State private var showParticles = false

    var body: some View {
        ZStack {
            if showParticles {
                CelebrationParticles(colors: [
                    mcSuccess, vm.themeVisuals.primary,
                    vm.themeVisuals.glow, .white
                ])
                .ignoresSafeArea()
            }

            VStack(spacing: 32) {
                Text("ALL MISSIONS")
                    .font(.system(size: 22, weight: .bold, design: .monospaced))
                    .tracking(8)
                    .foregroundColor(vm.themeVisuals.primary.opacity(0.7))
                    .opacity(showTitle ? 1 : 0)

                Text("Complete!")
                    .font(.system(size: 80, weight: .heavy))
                    .foregroundColor(.white)
                    .shadow(color: vm.themeVisuals.glow.opacity(0.4), radius: 30, y: 4)
                    .opacity(showTitle ? 1 : 0)
                    .scaleEffect(showTitle ? 1 : 0.9)

                Text("\(completed) of \(totalRounds) missions")
                    .font(.system(size: 32, weight: .medium))
                    .foregroundColor(.gray)
                    .opacity(showStats ? 1 : 0)
                    .offset(y: showStats ? 0 : 10)
            }
            .textBackdrop()
        }
        .onAppear {
            showParticles = true
            withAnimation(.easeOut(duration: 0.8)) {
                showTitle = true
            }
            withAnimation(.easeOut(duration: 0.6).delay(0.5)) {
                showStats = true
            }
        }
    }
}

// MARK: - Results

struct ResultsView: View {
    let results: GameResults
    @EnvironmentObject var vm: GameViewModel
    @State private var showContent = false
    @FocusState private var doneFocused: Bool

    var body: some View {
        ZStack {
            // Confetti burst at top
            if showContent {
                CelebrationParticles(colors: [
                    mcSuccess, vm.themeVisuals.primary,
                    vm.themeVisuals.glow, mcWarning, .white
                ])
                .ignoresSafeArea()
            }

            VStack(spacing: 24) {
                Text("Mission Complete!")
                    .font(.system(size: 52, weight: .heavy))
                    .foregroundColor(vm.themeVisuals.primary)
                    .shadow(color: vm.themeVisuals.glow.opacity(0.3), radius: 20)
                    .opacity(showContent ? 1 : 0)
                    .scaleEffect(showContent ? 1 : 0.9)

                Text("\(results.completed) of \(results.totalRounds) completed in \(String(format: "%.1f", results.totalTime))s")
                    .font(.title2.weight(.semibold))
                    .foregroundColor(.white)
                    .opacity(showContent ? 1 : 0)

                VStack(spacing: 4) {
                    ForEach(Array(results.results.enumerated()), id: \.element.id) { index, r in
                        HStack {
                            Text("#\(r.round)")
                                .lineLimit(1)
                                .fixedSize()
                                .frame(width: 80, alignment: .leading)
                                .foregroundColor(.gray)

                            Text(r.name)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .foregroundColor(.white)

                            Text(String(format: "%.1fs", r.time))
                                .font(.system(.body, design: .monospaced))
                                .frame(width: 100, alignment: .trailing)
                                .foregroundColor(.gray)

                            Text(r.status.capitalized)
                                .frame(width: 160, alignment: .trailing)
                                .lineLimit(1)
                                .foregroundColor(statusColor(r.status))
                                .fontWeight(.bold)
                        }
                        .font(.title3)
                        .padding(.vertical, 8)
                        .padding(.horizontal, 12)
                        .background(index % 2 == 0 ? Color.white.opacity(0.02) : .clear)
                        .cornerRadius(8)
                        .opacity(showContent ? 1 : 0)
                        .offset(x: showContent ? 0 : -30)
                        .animation(.easeOut(duration: 0.5).delay(Double(index) * 0.08 + 0.3), value: showContent)
                    }
                }
                .padding(.horizontal, 80)

                Button(action: { vm.disconnect() }) {
                    Text("Done")
                        .font(.title3.weight(.semibold))
                        .padding(.horizontal, 40)
                        .padding(.vertical, 12)
                        .background(doneFocused ? mcAccent.opacity(0.15) : mcCard)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(doneFocused ? mcAccent.opacity(0.5) : Color.white.opacity(0.1), lineWidth: doneFocused ? 2 : 1)
                        )
                        .foregroundColor(.white)
                        .cornerRadius(12)
                        .scaleEffect(doneFocused ? 1.05 : 1.0)
                        .shadow(color: doneFocused ? mcAccent.opacity(0.3) : .clear, radius: 8)
                        .animation(.easeInOut(duration: 0.15), value: doneFocused)
                }
                .buttonStyle(.mc)
                .focused($doneFocused)
                .padding(.top, 16)
                .opacity(showContent ? 1 : 0)
            }
            .textBackdrop(padding: 36)
            .padding(40)
        }
        .onAppear {
            withAnimation(.easeOut(duration: 0.6)) {
                showContent = true
            }
        }
    }

    func statusColor(_ status: String) -> Color {
        switch status {
        case "completed": return mcSuccess
        case "skipped": return mcWarning
        case "timeout": return mcDanger
        default: return .gray
        }
    }
}

// MARK: - Game Control Buttons

struct GameControlButtons: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var confirmEnd = false
    @FocusState private var skipFocused: Bool
    @FocusState private var endFocused: Bool

    var body: some View {
        HStack(spacing: 24) {
            Button {
                vm.skipRound()
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "forward.fill")
                    Text("Skip")
                }
                .font(.system(size: 20, weight: .semibold))
                .padding(.horizontal, 32)
                .padding(.vertical, 14)
                .background(skipFocused ? mcWarning.opacity(0.15) : mcCard)
                .foregroundColor(mcWarning)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(mcWarning.opacity(skipFocused ? 0.6 : 0.3), lineWidth: skipFocused ? 2 : 1)
                )
                .cornerRadius(14)
                .scaleEffect(skipFocused ? 1.05 : 1.0)
                .shadow(color: skipFocused ? mcWarning.opacity(0.3) : .clear, radius: 8)
                .animation(.easeInOut(duration: 0.15), value: skipFocused)
            }
            .buttonStyle(.mc)
            .focused($skipFocused)

            if confirmEnd {
                Button {
                    vm.stopGame()
                    confirmEnd = false
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                        Text("Confirm End")
                    }
                    .font(.system(size: 20, weight: .semibold))
                    .padding(.horizontal, 32)
                    .padding(.vertical, 14)
                    .background(endFocused ? mcDanger.opacity(0.25) : mcDanger.opacity(0.15))
                    .foregroundColor(mcDanger)
                    .overlay(
                        RoundedRectangle(cornerRadius: 14)
                            .stroke(mcDanger.opacity(endFocused ? 0.8 : 0.5), lineWidth: endFocused ? 2 : 1)
                    )
                    .cornerRadius(14)
                    .scaleEffect(endFocused ? 1.05 : 1.0)
                    .shadow(color: endFocused ? mcDanger.opacity(0.3) : .clear, radius: 8)
                    .animation(.easeInOut(duration: 0.15), value: endFocused)
                }
                .buttonStyle(.mc)
                .focused($endFocused)
            } else {
                Button {
                    confirmEnd = true
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "stop.fill")
                        Text("End Game")
                    }
                    .font(.system(size: 20, weight: .semibold))
                    .padding(.horizontal, 32)
                    .padding(.vertical, 14)
                    .background(endFocused ? mcDanger.opacity(0.12) : mcCard)
                    .foregroundColor(mcDanger.opacity(endFocused ? 1.0 : 0.7))
                    .overlay(
                        RoundedRectangle(cornerRadius: 14)
                            .stroke(mcDanger.opacity(endFocused ? 0.5 : 0.2), lineWidth: endFocused ? 2 : 1)
                    )
                    .cornerRadius(14)
                    .scaleEffect(endFocused ? 1.05 : 1.0)
                    .shadow(color: endFocused ? mcDanger.opacity(0.2) : .clear, radius: 8)
                    .animation(.easeInOut(duration: 0.15), value: endFocused)
                }
                .buttonStyle(.mc)
                .focused($endFocused)
            }
        }
    }
}

// MARK: - Difficulty Badge

struct DifficultyBadge: View {
    let difficulty: String

    private var color: Color {
        switch difficulty {
        case "easy": return mcSuccess
        case "medium": return mcWarning
        case "hard": return mcDanger
        default: return .gray
        }
    }

    var body: some View {
        Text(difficulty.uppercased())
            .font(.system(size: 16, weight: .bold, design: .monospaced))
            .tracking(3)
            .padding(.horizontal, 24)
            .padding(.vertical, 8)
            .background(color.opacity(0.12))
            .foregroundColor(color)
            .overlay(
                Capsule()
                    .stroke(color.opacity(0.3), lineWidth: 1)
            )
            .clipShape(Capsule())
    }
}
