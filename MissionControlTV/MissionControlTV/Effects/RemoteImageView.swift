import SwiftUI

// MARK: - Image Cache

class ImageCache {
    static let shared = ImageCache()
    private var cache: [String: UIImage] = [:]
    private var accessOrder: [String] = []
    private let maxEntries = 5

    func get(_ url: String) -> UIImage? {
        return cache[url]
    }

    func set(_ url: String, image: UIImage) {
        if cache[url] == nil {
            accessOrder.append(url)
        }
        cache[url] = image

        // Evict oldest if over limit
        while accessOrder.count > maxEntries {
            let oldest = accessOrder.removeFirst()
            cache.removeValue(forKey: oldest)
        }
    }
}

// MARK: - Image Loader

@MainActor
class RemoteImageLoader: ObservableObject {
    @Published var image: UIImage?
    @Published var isLoading = false
    private var currentURL: String?

    func load(from urlString: String) {
        guard urlString != currentURL else { return }
        currentURL = urlString

        // Check cache
        if let cached = ImageCache.shared.get(urlString) {
            self.image = cached
            return
        }

        guard let url = URL(string: urlString) else { return }

        isLoading = true
        Task {
            do {
                let (data, _) = try await URLSession.shared.data(from: url)
                if let img = UIImage(data: data) {
                    ImageCache.shared.set(urlString, image: img)
                    if currentURL == urlString {
                        self.image = img
                    }
                }
            } catch {
                // Silently fail — views fall back to gradient
            }
            if currentURL == urlString {
                isLoading = false
            }
        }
    }

    func clear() {
        image = nil
        currentURL = nil
    }
}

// MARK: - Remote Image View

struct RemoteImageView: View {
    let url: String?
    var blurRadius: CGFloat = 20
    var opacity: Double = 0.3
    var kenBurnsDuration: Double = 15

    @StateObject private var loader = RemoteImageLoader()

    var body: some View {
        Group {
            if let image = loader.image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .blur(radius: blurRadius)
                    .opacity(opacity)
                    .kenBurns(duration: kenBurnsDuration)
                    .transition(.opacity.animation(.easeIn(duration: 1.0)))
                    .clipped()
            }
        }
        .onChange(of: url) { _, newURL in
            if let newURL = newURL {
                loader.load(from: newURL)
            } else {
                loader.clear()
            }
        }
        .onAppear {
            if let url = url {
                loader.load(from: url)
            }
        }
    }
}
