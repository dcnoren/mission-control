# Mission Control

Cooperative smart home challenge game for kids using Home Assistant, ElevenLabs TTS, and speakers registered as `media_player` entities (Sonos, Google Home, Echo, etc.). Optional Apple TV companion mode via native tvOS app.

## Architecture

- **Backend**: FastAPI + uvicorn, single container, port 8765
- **Frontend**: Vanilla HTML/CSS/JS with browser WebSocket for real-time updates
- **tvOS App**: SwiftUI app connects via WebSocket for Apple TV display + audio
- **Infrastructure**: Docker container, data persisted in named volume (`mc-data`)
- **Integrations**: Home Assistant (WebSocket + REST), ElevenLabs (TTS + SFX), OpenRouter (LLM + image generation)
- **Storage**: `/app/data/` — `config.json`, `challenges.db` (SQLite), `cache/` (audio + images)

## Key Files

- `mission_control_v2/engine.py` — Core game loop, HA WebSocket monitoring, TTS generation, speaker routing, volume control
- `mission_control_v2/server.py` — FastAPI endpoints, WebSocket broadcast, config persistence, theme phrase overrides
- `mission_control_v2/challenges.py` — Challenge data model with targets, speakers, pre-setup steps
- `mission_control_v2/challenge_db.py` — SQLite-backed challenge storage (replaced legacy JSON)
- `mission_control_v2/challenge_gen.py` — LLM-powered challenge generation via OpenRouter (Claude Sonnet)
- `mission_control_v2/image_gen.py` — AI scene image generation via OpenRouter (Gemini 3 Pro Image Preview), hash-based caching
- `mission_control_v2/themes.py` — Theme definitions (Mission Control, Bluey, Snoop & Sniffy) with voice IDs, intros, outros
- `mission_control_v2/static/js/app.js` — Web dashboard UI logic
- `mission_control_v2/templates/index.html` — Single-page HTML template
- `MissionControlTV/` — Xcode tvOS app project (SwiftUI)

## Game Flow

1. User picks theme, rounds, difficulty on web dashboard
2. Engine connects to HA WebSocket, caches entity states
3. Intro music plays (ElevenLabs SFX, 30s), critical audio precached in parallel
4. Intro TTS announcement, then rounds begin (remaining audio caches in background)
5. Each round: pre-setup entities → announce challenge → monitor HA for completion (45s timeout, hint at 30s) → success announcement on room speaker
6. Finale with stats, then restore all entity states

## Apple TV Mode

Two launch modes:
- **Direct from Apple TV** — start a game from the Siri Remote
- **Subscribe from Apple TV, launch from Web UI** — Apple TV listens, web dashboard controls theme/rounds/difficulty/challenges

When launched with "Launch Mission (Apple TV)", hub audio is broadcast via WebSocket (`atv_play_audio` events) instead of playing on speakers. The tvOS app receives these events, plays audio via AVPlayer, and renders mission cards natively in SwiftUI. Room speakers still handle success messages. Inter-round advancement uses "Next Mission" button (on web dashboard or Apple TV remote via Menu button).

## Speaker Routing (`_resolve_speaker`)

| Mode | Hub Speaker | Room Speakers |
|------|------------|---------------|
| Normal | Hub speaker | Room speakers |
| Test | Test speaker | Test speaker |
| Apple TV | "appletv" (WebSocket) | Room speakers |
| Apple TV + Test | "appletv" (WebSocket) | Test speaker |

## Speaker Volume

Configurable via Settings UI slider (default 40%, persisted in config). All `media_player` volume calls use `engine.speaker_volume`. Intro music plays at 70% of the configured volume for a softer lead-in. Does not affect Apple TV hub audio (controlled by TV remote).

## Config

Persisted in `/app/data/config.json`. API keys (ElevenLabs, OpenRouter, HA token) set via Settings panel or environment variables. `server_url` must be the LAN-reachable address for audio file serving. `speaker_volume` is UI-only (no env var).

## Theme Phrase Overrides

Theme text (intros, outros, prefixes, hints, timeouts) is editable via the Settings > Theme Phrases UI. Overrides persist in `config.json` under `theme_phrases`. A "Reset to Default" restores from `_THEME_DEFAULTS` — a `copy.deepcopy` snapshot taken at import time in `server.py`. This is necessary because theme objects are mutable singletons.

## Deployment

- **Dev (Mac)**: `cd dev && docker compose up -d` — spins up a local Home Assistant instance with 31 fake devices across 7 rooms, auto-onboards, and starts mission-control on port 8765. HA is at localhost:8123 (login: dev/devdevdev). Fully automated — no manual setup needed. API keys go in `dev/.env`.
- **Prod**: Build for amd64 and push to GHCR, deploy via docker-compose on your server
  - Always build with: `docker buildx build --platform linux/amd64,linux/arm64 -t ghcr.io/dcnoren/mission-control:latest --push mission_control_v2/`
- **tvOS App**: Open `MissionControlTV/MissionControlTV.xcodeproj` in Xcode, run on Apple TV
  - Copy `Config.xcconfig.example` to `Config.xcconfig` and set your Team ID
  - `Config.xcconfig` is gitignored to keep developer credentials out of the repo

## Dev Environment Details

- `dev/docker-compose.yml` — HA + mission-control + one-shot setup container
- `dev/ha-config/configuration.yaml` — Template entities backed by `input_boolean` for all device types
- `dev/ha-config/custom_components/dev_speakers/` — Custom HA component providing fake `media_player` entities that accept play_media/volume_set/stop calls
- `dev/setup-ha.py` — Automated onboarding, token creation, area setup, entity assignment. Idempotent on re-runs.
- Entities are toggleable and fire proper `state_changed` WebSocket events
- Speakers won't produce actual audio but service calls succeed
- Don't run prod and dev at the same time (both use port 8765)

## Important Patterns

- Audio files cached by hash of text+voice in `/app/data/cache/`
- `play_cached_audio` resolves speaker routing, generates TTS if needed, uploads to HA media library, plays via `media_player.play_media`
- `needs_change_event` pattern: entities already in target state must leave and return before counting as complete
- Background audio caching: critical path (intro + first challenge) blocks, rest generates concurrently during gameplay
- Intro music: non-blocking broadcast, minimum 15s play time, fade out before voice intro
- Scene images: generated via OpenRouter (Gemini), cached by hash of prompt in `/app/data/cache/`
- ElevenLabs voices: changing voice IDs in themes.py automatically invalidates cached audio (voice ID is part of the hash)
- Exclamation marks in theme text cause stilted ElevenLabs audio — avoid them
