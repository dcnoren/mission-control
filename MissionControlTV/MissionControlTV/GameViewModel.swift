import SwiftUI
import AVFoundation
import Combine

// MARK: - App Navigation

enum AppMode: Equatable {
    case unconfigured    // first launch
    case home            // mode selection
    case localSetup      // configuring local launch
    case playing         // game in progress
}

// MARK: - Data Models

struct ThemeOption: Identifiable {
    let id: String    // slug
    let name: String  // display name
}

struct FloorOption: Identifiable {
    let id: String    // name
    let name: String
}

// MARK: - Game Screen (in-game only)

enum GameScreen {
    case waiting(String)
    case mission(MissionInfo)
    case timer(MissionInfo, Double)
    case roundComplete(String, Double)
    case waitingAdvance
    case finale(Int, Int)  // completed, totalRounds
    case results(GameResults)
}

struct MissionInfo: Equatable {
    let round: Int
    let totalRounds: Int
    let name: String
    let room: String
    let difficulty: String
}

struct RoundResult: Identifiable {
    let id = UUID()
    let round: Int
    let name: String
    let time: Double
    let status: String
}

struct GameResults {
    let completed: Int
    let totalRounds: Int
    let totalTime: Double
    let results: [RoundResult]
}

@MainActor
class GameViewModel: ObservableObject {
    // Navigation
    @Published var appMode: AppMode = .unconfigured
    @Published var screen: GameScreen = .waiting("Connecting...")
    @Published var screenId: Int = 0

    // Connection
    @Published var serverAddress: String = ""
    @Published var connected = false

    // Game state
    @Published var completedCount = 0
    @Published var totalTime: Double = 0

    // Config fetching
    @Published var themes: [ThemeOption] = []
    @Published var floors: [FloorOption] = []
    @Published var isLoadingConfig = false
    @Published var configError: String? = nil

    // Launch conflict
    @Published var gameAlreadyRunning = false

    // Settings sheet
    @Published var showSettings = false

    // Theme visuals
    @Published var themeVisuals: ThemeVisuals = .forTheme("mission_control")
    @Published var currentThemeName: String = "Mission Control"
    @Published var introImageURL: String? = nil
    @Published var sceneImageURL: String? = nil
    @Published var transitionImageURL: String? = nil
    @Published var outroImageURL: String? = nil
    @Published var showIntroSequence: Bool = false

    // Local setup selections
    @Published var selectedTheme: String = "mission_control"
    @Published var selectedDifficulty: String = "mixed"
    @Published var selectedRounds: Int = 5
    @Published var selectedFloors: Set<String> = []

    @AppStorage("serverAddress") private var savedAddress: String = ""
    @AppStorage("hasCompletedSetup") private var hasCompletedSetup: Bool = false

    private var webSocketTask: URLSessionWebSocketTask?
    private var player: AVPlayer?
    private var results: [RoundResult] = []
    private var currentMission: MissionInfo?

    init() {
        serverAddress = savedAddress
    }

    // MARK: - Computed

    var baseURL: String {
        let addr = savedAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        if addr.hasPrefix("http://") || addr.hasPrefix("https://") {
            return addr
        }
        return "http://\(addr)"
    }

    // MARK: - Initialization

    func initialize() {
        if hasCompletedSetup && !savedAddress.isEmpty {
            appMode = .home
        } else {
            appMode = .unconfigured
        }
    }

    // MARK: - Setup & Navigation

    func saveServerAddress(_ address: String) {
        let addr = address.trimmingCharacters(in: .whitespacesAndNewlines)
        savedAddress = addr
        serverAddress = addr
        hasCompletedSetup = true
        appMode = .home
    }

    func returnToHome() {
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        connected = false
        introImageURL = nil
        sceneImageURL = nil
        transitionImageURL = nil
        outroImageURL = nil
        showIntroSequence = false
        appMode = .home
    }

    func enterRemoteMode() {
        connectWebSocket()
        appMode = .playing
    }

    func startLocalGame() {
        guard let url = URL(string: "\(baseURL)/api/start") else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "theme": selectedTheme,
            "rounds": selectedRounds,
            "difficulty": selectedDifficulty,
            "appletv_mode": true,
            "floors": selectedFloors.isEmpty ? [] : Array(selectedFloors)
        ]

        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        gameAlreadyRunning = false
        appMode = .playing
        setScreen(.waiting("Starting mission..."))

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            Task { @MainActor in
                if let error = error {
                    self?.setScreen(.waiting("Error: \(error.localizedDescription)"))
                    return
                }
                if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 409 {
                    self?.gameAlreadyRunning = true
                    self?.appMode = .localSetup
                    return
                }
                // Connect WebSocket after successful start
                self?.connectWebSocket()
            }
        }.resume()
    }

    func stopAndRelaunch() {
        gameAlreadyRunning = false
        guard let url = URL(string: "\(baseURL)/api/stop") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request) { [weak self] _, _, _ in
            Task { @MainActor in
                // Brief delay to let the server finish stopping
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                self?.startLocalGame()
            }
        }.resume()
    }

    // MARK: - API Fetching

    func fetchThemesAndFloors() async {
        isLoadingConfig = true
        configError = nil

        async let themesResult = fetchThemes()
        async let floorsResult = fetchFloors()

        let (fetchedThemes, fetchedFloors) = await (themesResult, floorsResult)

        themes = fetchedThemes
        floors = fetchedFloors
        if selectedFloors.isEmpty {
            selectedFloors = Set(fetchedFloors.map { $0.id })
        }
        isLoadingConfig = false
    }

    func testConnection() async -> Bool {
        guard let url = URL(string: "\(baseURL)/api/themes") else { return false }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func fetchThemes() async -> [ThemeOption] {
        guard let url = URL(string: "\(baseURL)/api/themes") else { return [] }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Any]] {
                return json.compactMap { (slug, info) in
                    guard let name = info["name"] as? String else { return nil }
                    return ThemeOption(id: slug, name: name)
                }.sorted { $0.name < $1.name }
            }
        } catch {
            configError = "Failed to load themes"
        }
        return []
    }

    private func fetchFloors() async -> [FloorOption] {
        guard let url = URL(string: "\(baseURL)/api/config") else { return [] }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let floorsArray = json["floors"] as? [[String: Any]] {
                return floorsArray.compactMap { f in
                    guard let name = f["name"] as? String else { return nil }
                    return FloorOption(id: name, name: name)
                }
            }
        } catch {
            configError = "Failed to load floors"
        }
        return []
    }

    // MARK: - WebSocket

    private func connectWebSocket() {
        let addr = savedAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !addr.isEmpty else { return }

        let wsURL: String
        if addr.hasPrefix("http://") {
            wsURL = "ws://" + addr.dropFirst(7) + "/ws"
        } else if addr.hasPrefix("https://") {
            wsURL = "wss://" + addr.dropFirst(8) + "/ws"
        } else {
            wsURL = "ws://" + addr + "/ws"
        }

        guard let url = URL(string: wsURL) else { return }

        webSocketTask?.cancel()
        let session = URLSession(configuration: .default)
        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()
        connected = true
        receiveMessage()
    }

    // Keep legacy connect() for backwards compat with ConnectView pattern
    func connect() {
        let addr = serverAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !addr.isEmpty else { return }
        savedAddress = addr
        connectWebSocket()
        setScreen(.waiting("Connected. Waiting for game..."))
    }

    func disconnect() {
        returnToHome()
    }

    private func setScreen(_ newScreen: GameScreen) {
        screen = newScreen
        screenId += 1
    }

    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            Task { @MainActor in
                switch result {
                case .success(let message):
                    switch message {
                    case .string(let text):
                        self?.handleMessage(text)
                    default:
                        break
                    }
                    self?.receiveMessage()
                case .failure:
                    self?.connected = false
                }
            }
        }
    }

    private func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else { return }

        switch type {
        case "state_sync":
            if json["running"] as? Bool == true {
                setScreen(.waiting("Game in progress..."))
            } else if appMode == .playing {
                // Remote mode: waiting for game to start
                setScreen(.waiting("Connected. Waiting for game..."))
            }

        case "game_starting":
            completedCount = 0
            totalTime = 0
            results = []
            let theme = json["theme"] as? String ?? "Mission Control"
            let themeSlug = json["theme_slug"] as? String ?? "mission_control"
            currentThemeName = theme
            themeVisuals = .forTheme(themeSlug)
            if let introURL = json["intro_image_url"] as? String {
                introImageURL = introURL
            }
            showIntroSequence = true
            setScreen(.waiting("Starting \(theme)..."))

        case "precaching":
            let msg = json["message"] as? String ?? "Preparing audio..."
            setScreen(.waiting(msg))

        case "precaching_progress":
            let gen = json["generated"] as? Int ?? 0
            let total = json["total"] as? Int ?? 0
            setScreen(.waiting("Generating audio: \(gen)/\(total)..."))

        case "precaching_done":
            setScreen(.waiting("Audio ready. Get ready..."))

        case "game_started":
            showIntroSequence = false
            setScreen(.waiting("Get ready..."))

        case "round_starting":
            let challenge = json["challenge"] as? [String: Any] ?? [:]
            let mission = MissionInfo(
                round: json["round"] as? Int ?? 0,
                totalRounds: json["total_rounds"] as? Int ?? 0,
                name: challenge["name"] as? String ?? "",
                room: challenge["room"] as? String ?? "",
                difficulty: challenge["difficulty"] as? String ?? "easy"
            )
            currentMission = mission
            if let sceneURL = json["scene_image_url"] as? String {
                sceneImageURL = sceneURL
            }
            setScreen(.mission(mission))

            if let audioURL = json["audio_url"] as? String {
                playAudio(audioURL)
            }

        case "timer_tick":
            if let mission = currentMission {
                let elapsed = json["elapsed"] as? Double ?? 0
                setScreen(.timer(mission, elapsed))
            }

        case "round_complete", "round_skipped":
            let status = json["status"] as? String ?? "unknown"
            let time = json["time"] as? Double ?? 0
            let name = json["challenge_name"] as? String ?? ""
            let round = json["round"] as? Int ?? 0

            results.append(RoundResult(round: round, name: name, time: time, status: status))

            if status == "completed" {
                completedCount += 1
                totalTime += time
                setScreen(.roundComplete(name, time))
            } else if round < (currentMission?.totalRounds ?? 0) {
                setScreen(.waiting("Next round coming up..."))
            } else {
                setScreen(.waiting("Wrapping up..."))
            }

            if let audioURL = json["audio_url"] as? String {
                playAudio(audioURL)
            }

        case "atv_waiting_for_advance":
            if let transURL = json["transition_image_url"] as? String {
                transitionImageURL = transURL
            }
            setScreen(.waitingAdvance)

        case "finale":
            let completed = json["completed"] as? Int ?? 0
            let totalRounds = json["total_rounds"] as? Int ?? 0
            if let outroURL = json["outro_image_url"] as? String {
                outroImageURL = outroURL
            }
            setScreen(.finale(completed, totalRounds))

        case "game_finished":
            let completed = json["completed"] as? Int ?? 0
            let totalRounds = json["total_rounds"] as? Int ?? 0
            let totalTime = json["total_time"] as? Double ?? 0
            let resultData = json["results"] as? [[String: Any]] ?? []
            let roundResults = resultData.map { r in
                RoundResult(
                    round: r["round"] as? Int ?? 0,
                    name: r["challenge_name"] as? String ?? "",
                    time: r["time"] as? Double ?? 0,
                    status: r["status"] as? String ?? ""
                )
            }
            if let outroURL = json["outro_image_url"] as? String {
                outroImageURL = outroURL
            }
            setScreen(.results(GameResults(
                completed: completed,
                totalRounds: totalRounds,
                totalTime: totalTime,
                results: roundResults
            )))

            if let audioURL = json["audio_url"] as? String {
                playAudio(audioURL)
            }

        case "game_stopped":
            setScreen(.results(GameResults(
                completed: completedCount,
                totalRounds: currentMission?.totalRounds ?? 0,
                totalTime: totalTime,
                results: results
            )))

        case "atv_play_audio":
            if let audioURL = json["audio_url"] as? String {
                playAudio(audioURL)
            }

        case "atv_fade_out":
            fadeOutAudio()

        case "error":
            let msg = json["message"] as? String ?? "Unknown error"
            setScreen(.waiting("Error: \(msg)"))

        default:
            break
        }
    }

    func advance() {
        guard let url = URL(string: "\(baseURL)/api/advance") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request).resume()
        setScreen(.waiting("Starting next mission..."))
    }

    func skipRound() {
        guard let url = URL(string: "\(baseURL)/api/skip") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request).resume()
    }

    func stopGame() {
        guard let url = URL(string: "\(baseURL)/api/stop") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request).resume()
    }

    private func playAudio(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        if player == nil {
            player = AVPlayer()
        }
        player?.pause()
        player?.replaceCurrentItem(with: nil)
        let item = AVPlayerItem(url: url)
        player?.replaceCurrentItem(with: item)
        player?.volume = 1.0
        player?.play()
    }

    private func fadeOutAudio() {
        guard let player = player else { return }
        let steps = 6
        let stepTime = 0.4
        for i in 1...steps {
            let volume = Float(1.0 - Double(i) / Double(steps))
            DispatchQueue.main.asyncAfter(deadline: .now() + stepTime * Double(i)) { [weak player] in
                player?.volume = max(volume, 0)
                if i == steps {
                    player?.pause()
                    player?.volume = 1.0
                }
            }
        }
    }
}
