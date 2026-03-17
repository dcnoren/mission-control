import SwiftUI

// MARK: - Cinematic Transition Modifiers

struct CinematicModifier: ViewModifier {
    let active: Bool

    func body(content: Content) -> some View {
        content
            .scaleEffect(active ? 1.0 : 0.92)
            .blur(radius: active ? 0 : 8)
            .opacity(active ? 1 : 0)
    }
}

struct SlideBlurModifier: ViewModifier {
    let active: Bool

    func body(content: Content) -> some View {
        content
            .offset(x: active ? 0 : 60)
            .blur(radius: active ? 0 : 6)
            .opacity(active ? 1 : 0)
    }
}

struct DramaticModifier: ViewModifier {
    let active: Bool

    func body(content: Content) -> some View {
        content
            .scaleEffect(active ? 1.0 : 1.08)
            .opacity(active ? 1 : 0)
    }
}

// MARK: - AnyTransition Extensions

extension AnyTransition {
    static var cinematic: AnyTransition {
        .modifier(
            active: CinematicModifier(active: false),
            identity: CinematicModifier(active: true)
        )
    }

    static var slideBlur: AnyTransition {
        .modifier(
            active: SlideBlurModifier(active: false),
            identity: SlideBlurModifier(active: true)
        )
    }

    static var dramatic: AnyTransition {
        .modifier(
            active: DramaticModifier(active: false),
            identity: DramaticModifier(active: true)
        )
    }
}

// MARK: - Vignette Overlay

struct VignetteOverlay: View {
    var intensity: Double = 0.6

    var body: some View {
        RadialGradient(
            colors: [.clear, .black.opacity(intensity)],
            center: .center,
            startRadius: 300,
            endRadius: 900
        )
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}

// MARK: - Text Backdrop

struct TextBackdrop: View {
    var padding: CGFloat = 48
    var cornerRadius: CGFloat = 24
    var opacity: Double = 0.55

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius)
            .fill(.black.opacity(opacity))
            .padding(-padding)
            .allowsHitTesting(false)
    }
}

extension View {
    func textBackdrop(padding: CGFloat = 48, opacity: Double = 0.55) -> some View {
        self.background(
            TextBackdrop(padding: padding, opacity: opacity)
        )
    }
}

// MARK: - MC Button Style (suppresses tvOS system focus chrome)

struct MCButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.7 : 1.0)
            .animation(.easeInOut(duration: 0.1), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == MCButtonStyle {
    static var mc: MCButtonStyle { MCButtonStyle() }
}

// MARK: - Ken Burns Effect

struct KenBurnsModifier: ViewModifier {
    let duration: Double
    @State private var scale: CGFloat = 1.0

    func body(content: Content) -> some View {
        content
            .scaleEffect(scale)
            .onAppear {
                withAnimation(.linear(duration: duration)) {
                    scale = 1.05
                }
            }
    }
}

extension View {
    func kenBurns(duration: Double = 15) -> some View {
        modifier(KenBurnsModifier(duration: duration))
    }
}
