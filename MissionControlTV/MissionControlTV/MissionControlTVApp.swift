import SwiftUI

@main
struct MissionControlTVApp: App {
    @StateObject private var gameVM = GameViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(gameVM)
                .onAppear {
                    gameVM.initialize()
                }
        }
    }
}
