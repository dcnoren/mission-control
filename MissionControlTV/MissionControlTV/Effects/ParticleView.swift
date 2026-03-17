import SwiftUI

enum ParticleStyle {
    case drift      // gentle random wandering
    case rise       // float upward like bubbles
    case sparkle    // twinkle in place
    case firework   // burst outward from center
}

struct ParticleConfig {
    var count: Int = 40
    var colors: [Color] = [.white]
    var minSize: CGFloat = 2
    var maxSize: CGFloat = 6
    var speed: CGFloat = 0.2
    var style: ParticleStyle = .drift
}

struct Particle {
    var x: CGFloat
    var y: CGFloat
    var size: CGFloat
    var opacity: Double
    var colorIndex: Int
    var velocityX: CGFloat
    var velocityY: CGFloat
    var phase: Double  // for sparkle timing
    var life: Double   // 0..1 for firework
}

struct ParticleView: View {
    let config: ParticleConfig
    @State private var particles: [Particle] = []
    @State private var size: CGSize = .zero

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0)) { timeline in
            Canvas { context, canvasSize in
                for p in particles {
                    let color = config.colors[p.colorIndex % config.colors.count]
                    let rect = CGRect(
                        x: p.x - p.size / 2,
                        y: p.y - p.size / 2,
                        width: p.size,
                        height: p.size
                    )
                    context.opacity = p.opacity
                    context.fill(
                        Circle().path(in: rect),
                        with: .color(color)
                    )
                    // Add glow for larger particles
                    if p.size > config.minSize + 1 {
                        let glowRect = CGRect(
                            x: p.x - p.size,
                            y: p.y - p.size,
                            width: p.size * 2,
                            height: p.size * 2
                        )
                        context.opacity = p.opacity * 0.15
                        context.fill(
                            Circle().path(in: glowRect),
                            with: .color(color)
                        )
                    }
                }
            }
            .onChange(of: timeline.date) { _, _ in
                updateParticles()
            }
        }
        .background(GeometryReader { geo in
            Color.clear.onAppear {
                size = geo.size
                initializeParticles()
            }
            .onChange(of: geo.size) { _, newSize in
                size = newSize
            }
        })
        .allowsHitTesting(false)
    }

    private func initializeParticles() {
        guard size.width > 0 && size.height > 0 else { return }
        particles = (0..<config.count).map { _ in
            makeParticle(randomPosition: true)
        }
    }

    private func makeParticle(randomPosition: Bool) -> Particle {
        let x: CGFloat
        let y: CGFloat
        let vx: CGFloat
        let vy: CGFloat

        switch config.style {
        case .drift:
            x = randomPosition ? CGFloat.random(in: 0...size.width) : CGFloat.random(in: 0...size.width)
            y = randomPosition ? CGFloat.random(in: 0...size.height) : CGFloat.random(in: 0...size.height)
            vx = CGFloat.random(in: -config.speed...config.speed)
            vy = CGFloat.random(in: -config.speed...config.speed)
        case .rise:
            x = CGFloat.random(in: 0...size.width)
            y = randomPosition ? CGFloat.random(in: 0...size.height) : size.height + 10
            vx = CGFloat.random(in: -config.speed * 0.3...config.speed * 0.3)
            vy = -CGFloat.random(in: config.speed * 0.3...config.speed)
        case .sparkle:
            x = CGFloat.random(in: 0...size.width)
            y = CGFloat.random(in: 0...size.height)
            vx = 0
            vy = 0
        case .firework:
            let angle = CGFloat.random(in: 0...(.pi * 2))
            let speed = CGFloat.random(in: config.speed * 2...config.speed * 5)
            x = size.width / 2
            y = size.height / 2
            vx = cos(angle) * speed
            vy = sin(angle) * speed
        }

        return Particle(
            x: x,
            y: y,
            size: CGFloat.random(in: config.minSize...config.maxSize),
            opacity: Double.random(in: 0.2...0.7),
            colorIndex: Int.random(in: 0..<max(config.colors.count, 1)),
            velocityX: vx,
            velocityY: vy,
            phase: Double.random(in: 0...(.pi * 2)),
            life: 1.0
        )
    }

    private func updateParticles() {
        guard size.width > 0 && size.height > 0 else { return }

        for i in particles.indices {
            particles[i].x += particles[i].velocityX
            particles[i].y += particles[i].velocityY

            switch config.style {
            case .drift:
                // Gentle drift with slight direction changes
                particles[i].velocityX += CGFloat.random(in: -0.02...0.02)
                particles[i].velocityY += CGFloat.random(in: -0.02...0.02)
                particles[i].velocityX = max(-config.speed, min(config.speed, particles[i].velocityX))
                particles[i].velocityY = max(-config.speed, min(config.speed, particles[i].velocityY))
                particles[i].phase += 0.02
                particles[i].opacity = 0.3 + 0.3 * sin(particles[i].phase)

                // Wrap around edges
                if particles[i].x < -10 { particles[i].x = size.width + 10 }
                if particles[i].x > size.width + 10 { particles[i].x = -10 }
                if particles[i].y < -10 { particles[i].y = size.height + 10 }
                if particles[i].y > size.height + 10 { particles[i].y = -10 }

            case .rise:
                particles[i].velocityX += CGFloat.random(in: -0.01...0.01)
                particles[i].phase += 0.03
                particles[i].opacity = 0.3 + 0.3 * sin(particles[i].phase)

                if particles[i].y < -20 {
                    particles[i] = makeParticle(randomPosition: false)
                }

            case .sparkle:
                particles[i].phase += 0.05
                particles[i].opacity = 0.1 + 0.5 * abs(sin(particles[i].phase))

            case .firework:
                particles[i].life -= 0.015
                particles[i].opacity = max(0, particles[i].life)
                particles[i].velocityX *= 0.98
                particles[i].velocityY *= 0.98
                particles[i].velocityY += 0.02  // gravity

                if particles[i].life <= 0 {
                    particles[i] = makeParticle(randomPosition: false)
                }
            }
        }
    }
}

// Convenience for celebration bursts
struct CelebrationParticles: View {
    let colors: [Color]
    @State private var particles: [Particle] = []
    @State private var size: CGSize = .zero
    @State private var active = true

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0)) { timeline in
            Canvas { context, canvasSize in
                for p in particles where p.opacity > 0.01 {
                    let color = colors[p.colorIndex % colors.count]
                    let rect = CGRect(
                        x: p.x - p.size / 2,
                        y: p.y - p.size / 2,
                        width: p.size,
                        height: p.size
                    )
                    context.opacity = p.opacity
                    context.fill(
                        RoundedRectangle(cornerRadius: 1).path(in: rect),
                        with: .color(color)
                    )
                }
            }
            .onChange(of: timeline.date) { _, _ in
                updateConfetti()
            }
        }
        .background(GeometryReader { geo in
            Color.clear.onAppear {
                size = geo.size
                spawnConfetti()
            }
        })
        .allowsHitTesting(false)
    }

    private func spawnConfetti() {
        guard size.width > 0 else { return }
        particles = (0..<60).map { _ in
            let angle = CGFloat.random(in: -CGFloat.pi * 0.8 ... -CGFloat.pi * 0.2)
            let speed = CGFloat.random(in: 3...8)
            return Particle(
                x: CGFloat.random(in: size.width * 0.3...size.width * 0.7),
                y: size.height * 0.1,
                size: CGFloat.random(in: 3...8),
                opacity: 1.0,
                colorIndex: Int.random(in: 0..<max(colors.count, 1)),
                velocityX: cos(angle) * speed,
                velocityY: sin(angle) * speed,
                phase: 0,
                life: 1.0
            )
        }
    }

    private func updateConfetti() {
        for i in particles.indices {
            particles[i].x += particles[i].velocityX
            particles[i].y += particles[i].velocityY
            particles[i].velocityY += 0.08  // gravity
            particles[i].velocityX *= 0.99
            particles[i].life -= 0.008
            particles[i].opacity = max(0, particles[i].life)
        }
    }
}
