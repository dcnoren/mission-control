import SwiftUI

struct HomeView: View {
    @EnvironmentObject var vm: GameViewModel
    @State private var showTitle = false
    @State private var showCards = false
    @FocusState private var gearFocused: Bool

    var body: some View {
        ZStack(alignment: .topTrailing) {
            VStack(spacing: 48) {
                // Title
                VStack(spacing: 12) {
                    Text("MISSION")
                        .font(.system(size: 28, weight: .bold, design: .monospaced))
                        .tracking(16)
                        .foregroundColor(mcAccent.opacity(0.5))

                    Text("Control")
                        .font(.system(size: 84, weight: .heavy))
                        .foregroundColor(.white)
                        .shadow(color: mcAccent.opacity(0.3), radius: 30, y: 4)
                }
                .opacity(showTitle ? 1 : 0)
                .scaleEffect(showTitle ? 1 : 0.9)

                // Mode cards + gear in same focus row
                HStack(spacing: 40) {
                    ModeCard(
                        icon: "paperplane.fill",
                        title: "LAUNCH FROM TV",
                        subtitle: "Pick a theme and\nstart right here",
                        color: mcAccent
                    ) {
                        vm.appMode = .localSetup
                    }
                    .opacity(showCards ? 1 : 0)
                    .offset(y: showCards ? 0 : 30)

                    ModeCard(
                        icon: "desktopcomputer",
                        title: "REMOTE MANAGED",
                        subtitle: "Start from the\nweb dashboard",
                        color: mcAccent
                    ) {
                        vm.enterRemoteMode()
                    }
                    .opacity(showCards ? 1 : 0)
                    .offset(y: showCards ? 0 : 30)
                    .animation(.spring(response: 0.5, dampingFraction: 0.8).delay(0.1), value: showCards)
                }
            }

            // Gear button — top-right, in same focus space as cards
            Button {
                vm.showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 28))
                    .foregroundColor(gearFocused ? mcAccent : .gray.opacity(0.6))
                    .padding(20)
                    .scaleEffect(gearFocused ? 1.15 : 1.0)
                    .shadow(color: gearFocused ? mcAccent.opacity(0.3) : .clear, radius: 8)
                    .animation(.easeInOut(duration: 0.15), value: gearFocused)
            }
            .buttonStyle(.mc)
            .focused($gearFocused)
            .opacity(showTitle ? 1 : 0)
        }
        .padding(60)
        .onAppear {
            withAnimation(.easeOut(duration: 0.6)) {
                showTitle = true
            }
            withAnimation(.spring(response: 0.5, dampingFraction: 0.8).delay(0.3)) {
                showCards = true
            }
        }
        .onDisappear {
            showTitle = false
            showCards = false
        }
    }
}

// MARK: - Mode Card

struct ModeCard: View {
    let icon: String
    let title: String
    let subtitle: String
    let color: Color
    let action: () -> Void
    @FocusState private var isFocused: Bool

    var body: some View {
        Button(action: action) {
            VStack(spacing: 24) {
                Image(systemName: icon)
                    .font(.system(size: 52))
                    .foregroundColor(color)
                    .shadow(color: color.opacity(0.3), radius: 12)

                Text(title)
                    .font(.system(size: 22, weight: .bold, design: .monospaced))
                    .tracking(3)
                    .foregroundColor(.white)

                Text(subtitle)
                    .font(.title3)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
            .frame(width: 420, height: 300)
            .background(mcCard)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(color.opacity(isFocused ? 0.5 : 0.2), lineWidth: isFocused ? 2 : 1)
            )
            .cornerRadius(20)
            .scaleEffect(isFocused ? 1.03 : 1.0)
            .shadow(color: isFocused ? color.opacity(0.3) : .clear, radius: 12)
            .animation(.easeInOut(duration: 0.15), value: isFocused)
        }
        .buttonStyle(.mc)
        .focused($isFocused)
    }
}
