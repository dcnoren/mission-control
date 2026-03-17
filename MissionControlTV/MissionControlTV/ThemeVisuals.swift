import SwiftUI

struct ThemeVisuals {
    let primary: Color
    let secondary: Color
    let glow: Color
    let gradientStart: Color
    let gradientEnd: Color
    let particleConfig: ParticleConfig

    var backgroundGradient: LinearGradient {
        LinearGradient(
            colors: [gradientStart, gradientEnd],
            startPoint: .top,
            endPoint: .bottom
        )
    }

    var radialGlow: RadialGradient {
        RadialGradient(
            colors: [primary.opacity(0.08), .clear],
            center: .top,
            startRadius: 100,
            endRadius: 800
        )
    }

    static func forTheme(_ slug: String) -> ThemeVisuals {
        switch slug {
        case "bluey":
            return ThemeVisuals(
                primary: Color(red: 0.95, green: 0.60, blue: 0.20),
                secondary: Color(red: 0.40, green: 0.75, blue: 0.95),
                glow: Color(red: 0.95, green: 0.85, blue: 0.40),
                gradientStart: Color(red: 0.10, green: 0.25, blue: 0.30),
                gradientEnd: Color(red: 0.05, green: 0.15, blue: 0.30),
                particleConfig: ParticleConfig(
                    count: 35,
                    colors: [
                        Color(red: 0.55, green: 0.80, blue: 0.95),
                        Color(red: 0.95, green: 0.60, blue: 0.20),
                        Color(red: 0.95, green: 0.70, blue: 0.75),
                    ],
                    minSize: 4,
                    maxSize: 12,
                    speed: 0.3,
                    style: .rise
                )
            )
        case "snoop_and_sniffy":
            return ThemeVisuals(
                primary: Color(red: 0.90, green: 0.70, blue: 0.30),
                secondary: Color(red: 0.55, green: 0.40, blue: 0.25),
                glow: Color(red: 0.90, green: 0.75, blue: 0.35),
                gradientStart: Color(red: 0.15, green: 0.10, blue: 0.06),
                gradientEnd: Color(red: 0.10, green: 0.10, blue: 0.10),
                particleConfig: ParticleConfig(
                    count: 30,
                    colors: [
                        Color(red: 0.90, green: 0.70, blue: 0.30),
                        Color(red: 0.80, green: 0.60, blue: 0.30),
                        Color(red: 0.95, green: 0.85, blue: 0.50),
                    ],
                    minSize: 2,
                    maxSize: 6,
                    speed: 0.2,
                    style: .drift
                )
            )
        default: // mission_control
            return ThemeVisuals(
                primary: Color(red: 0.22, green: 0.74, blue: 0.97),
                secondary: Color(red: 0.40, green: 0.55, blue: 0.70),
                glow: Color(red: 0.22, green: 0.74, blue: 0.97),
                gradientStart: Color(red: 0.02, green: 0.04, blue: 0.12),
                gradientEnd: Color(red: 0.04, green: 0.06, blue: 0.10),
                particleConfig: ParticleConfig(
                    count: 40,
                    colors: [
                        Color(red: 0.22, green: 0.74, blue: 0.97),
                        Color(red: 0.40, green: 0.80, blue: 1.0),
                        Color.white,
                    ],
                    minSize: 1,
                    maxSize: 4,
                    speed: 0.15,
                    style: .drift
                )
            )
        }
    }
}
