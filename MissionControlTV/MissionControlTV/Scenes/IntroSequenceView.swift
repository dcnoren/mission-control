import SwiftUI

struct IntroSequenceView: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var showTitle = false
    @State private var showGetReady = false
    @State private var titleText = ""
    @State private var typewriterIndex = 0

    private var themeName: String {
        vm.currentThemeName
    }

    private var visuals: ThemeVisuals {
        vm.themeVisuals
    }

    var body: some View {
        ZStack {
            // Background scene image
            RemoteImageView(
                url: vm.introImageURL,
                blurRadius: 4,
                opacity: 0.65,
                kenBurnsDuration: 20
            )
            .ignoresSafeArea()

            // Subtle particle overlay
            ParticleView(config: visuals.particleConfig)
                .ignoresSafeArea()
                .opacity(0.3)

            // Light vignette for text readability
            VignetteOverlay(intensity: 0.35)

            // Content
            VStack(spacing: 40) {
                Spacer()

                // Theme name - typewriter effect
                Text(titleText)
                    .font(.system(size: 28, weight: .bold, design: .monospaced))
                    .tracking(12)
                    .foregroundColor(visuals.primary.opacity(0.7))
                    .opacity(showTitle ? 1 : 0)

                Text(themeName)
                    .font(.system(size: 90, weight: .heavy))
                    .foregroundColor(.white)
                    .shadow(color: visuals.glow.opacity(0.4), radius: 30, y: 4)
                    .opacity(showTitle ? 1 : 0)
                    .scaleEffect(showTitle ? 1 : 0.9)

                Spacer()

                // GET READY text
                Text("GET READY")
                    .font(.system(size: 36, weight: .heavy, design: .monospaced))
                    .tracking(16)
                    .foregroundColor(visuals.glow)
                    .shadow(color: visuals.glow.opacity(0.5), radius: 20)
                    .opacity(showGetReady ? 1 : 0)
                    .scaleEffect(showGetReady ? 1 : 0.8)

                Spacer()
                    .frame(height: 60)
            }
        }
        .onAppear {
            startTypewriter()
            withAnimation(.easeOut(duration: 1.2).delay(0.5)) {
                showTitle = true
            }
            withAnimation(.easeOut(duration: 0.8).delay(3.0)) {
                showGetReady = true
            }
        }
    }

    private func startTypewriter() {
        let target = "INCOMING TRANSMISSION"
        let chars = Array(target)
        typewriterIndex = 0
        titleText = ""

        func typeNext() {
            guard typewriterIndex < chars.count else { return }
            titleText += String(chars[typewriterIndex])
            typewriterIndex += 1
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.06) {
                typeNext()
            }
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            typeNext()
        }
    }
}
