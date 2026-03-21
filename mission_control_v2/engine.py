"""Game engine for Mission Control."""
import asyncio
import base64
import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse, urlunparse

import aiohttp
from mutagen.mp3 import MP3

from challenge_db import ChallengeDB
from challenges import Challenge, Difficulty, Target
from image_gen import ImageGenerator
from themes import ALL_THEMES, Theme, VoiceSettings

logger = logging.getLogger("mission_control.engine")

ROUND_TIMEOUT = 45
HINT_TIME = 30
DEFAULT_SPEAKER_VOLUME = 0.40

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVENLABS_SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

INTRO_MUSIC_VOLUME_RATIO = 0.70  # intro music plays at 70% of speaker volume
FADE_STEPS = 6
FADE_STEP_TIME = 0.4

HA_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
ELEVENLABS_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)

TEST_SPEAKER = "media_player.test_speaker"

MAX_WS_RECONNECT_ATTEMPTS = 3


NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy",
    80: "eighty", 90: "ninety",
}


def _ha_url_to_ws(ha_url: str) -> str:
    """Convert an HA HTTP URL to its WebSocket equivalent (scheme only)."""
    parsed = urlparse(ha_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(parsed._replace(scheme=ws_scheme)) + "/api/websocket"


def _seconds_to_words(time_str: str) -> str:
    """Convert a time like '5.0' or '12.3' to spoken words like 'five' or 'twelve'."""
    try:
        n = int(round(float(time_str)))
    except (ValueError, TypeError):
        return time_str

    if n in NUM_WORDS:
        return NUM_WORDS[n]
    if n < 100:
        tens = (n // 10) * 10
        ones = n % 10
        if ones == 0:
            return NUM_WORDS.get(tens, str(n))
        return f"{NUM_WORDS.get(tens, str(tens))} {NUM_WORDS.get(ones, str(ones))}"
    if n < 200:
        rest = n - 100
        if rest == 0:
            return "one hundred"
        return f"one hundred and {_seconds_to_words(str(rest))}"
    if n < 1000:
        hundreds = n // 100
        rest = n % 100
        if rest == 0:
            return f"{NUM_WORDS[hundreds]} hundred"
        return f"{NUM_WORDS[hundreds]} hundred and {_seconds_to_words(str(rest))}"
    return str(n)


def _cache_key(text: str, voice_id: str, voice_settings: VoiceSettings | None = None) -> str:
    """Generate a cache filename from text + voice + settings."""
    parts = f"{voice_id}:{text}"
    if voice_settings:
        parts += f":{voice_settings.stability}:{voice_settings.similarity_boost}:{voice_settings.style}:{voice_settings.speed}"
    h = hashlib.sha256(parts.encode()).hexdigest()[:16]
    return f"{h}.mp3"


def _get_mp3_duration(filepath: str | Path) -> float:
    """Get actual MP3 duration in seconds using mutagen."""
    try:
        audio = MP3(str(filepath))
        return audio.info.length + 0.5  # small buffer for playback start
    except Exception as e:
        logger.warning(f"Could not read MP3 duration: {e}")
        return 5.0  # safe fallback


class GameEngine:
    def __init__(
        self,
        ha_url: str,
        ha_token: str,
        elevenlabs_api_key: str,
        broadcast: Callable,
        cache_dir: str = "/app/data/cache",
        server_url: str = "",
        openrouter_api_key: str = "",
    ):
        self.ha_url = ha_url.rstrip("/")
        self.ha_ws_url = _ha_url_to_ws(self.ha_url)
        self.ha_token = ha_token
        self.elevenlabs_api_key = elevenlabs_api_key
        self.broadcast = broadcast
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.server_url = server_url
        self.openrouter_api_key = openrouter_api_key
        self.image_gen: ImageGenerator | None = None

        self.state_cache: dict[str, str] = {}
        self.original_states: dict[str, str] = {}
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.ws_session: Optional[aiohttp.ClientSession] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self.ws_msg_id = 0
        self.running = False
        self.current_round = 0
        self.total_rounds = 0
        self.results: list[dict] = []
        self.skip_requested = False
        self.stop_requested = False
        self.test_mode = False
        self.test_speaker = TEST_SPEAKER

        # Apple TV mode — tvOS app connects via WebSocket for audio/visuals
        self.appletv_mode = False
        self.advance_event: asyncio.Event = asyncio.Event()

        # Track which files have been uploaded to HA this session
        self._ha_uploaded: set[str] = set()

        # Hub speaker default
        self.hub_speaker = "media_player.hub_speaker"

        # Configurable speaker volume (0.0–1.0)
        self.speaker_volume = DEFAULT_SPEAKER_VOLUME

        # Challenge database
        self.challenge_db = ChallengeDB()

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """Get or create a reusable HTTP session."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _close_http_session(self):
        """Close the reusable HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

    def _get_image_gen(self) -> ImageGenerator | None:
        """Get or create ImageGenerator if API key is available."""
        if not self.openrouter_api_key:
            return None
        if self.image_gen is None or self.image_gen.api_key != self.openrouter_api_key:
            self.image_gen = ImageGenerator(self.openrouter_api_key, str(self.cache_dir))
        return self.image_gen

    def _get_cached_image_url(self, prompt: str) -> str | None:
        """Return URL for a cached image if it exists, without generating."""
        gen = self._get_image_gen()
        if not gen:
            return None
        filename = gen.cached_filename(prompt)
        if filename:
            return f"{self.server_url}/images/{filename}"
        return None

    async def _generate_scene_image(self, prompt: str) -> str | None:
        """Generate a scene image, return URL path or None."""
        gen = self._get_image_gen()
        if not gen:
            return None
        filename = await gen.generate(prompt)
        if filename:
            return f"{self.server_url}/images/{filename}"
        return None

    async def _precache_images(self, theme: Theme, challenges: list[Challenge]):
        """Background task: generate all scene images for a game.

        Priority order: per-room images first (needed soonest during gameplay),
        then transition, then outro. Intro is handled separately before this starts.
        """
        try:
            gen = self._get_image_gen()
            if not gen:
                return

            # Per-room images first — these are needed as rounds start
            room_prompts = []
            for c in challenges:
                if theme.mission_scene_template:
                    prompt = theme.mission_scene_template.format(room=c.room)
                    if prompt not in room_prompts:
                        room_prompts.append(prompt)

            # Then transition and outro
            other_prompts = []
            if theme.transition_prompt:
                other_prompts.append(theme.transition_prompt)
            if theme.outro_scene_prompt:
                other_prompts.append(theme.outro_scene_prompt)

            all_prompts = room_prompts + other_prompts
            generated = 0
            for prompt in all_prompts:
                if self.stop_requested:
                    break
                if not gen.is_cached(prompt):
                    await gen.generate(prompt)
                    generated += 1

            logger.info(f"Background image precache complete ({generated} generated, {len(all_prompts) - generated} cached)")
        except Exception as e:
            logger.error(f"Background image cache error: {e}")

    def update_ha_url(self, ha_url: str):
        """Update HA URL and derive WebSocket URL safely."""
        self.ha_url = ha_url.rstrip("/")
        self.ha_ws_url = _ha_url_to_ws(self.ha_url)

    def _resolve_speaker(self, speaker: str) -> str:
        """Resolve speaker routing based on mode.
        Apple TV mode: hub speaker content → 'appletv' sentinel.
        Test mode: non-hub speakers → test speaker.
        Apple TV + Test: hub → Apple TV, rooms → test speaker."""
        if self.appletv_mode and speaker == self.hub_speaker:
            return "appletv"
        if self.test_mode:
            return self.test_speaker
        return speaker

    # --- ElevenLabs Direct TTS ---

    async def generate_tts(self, text: str, voice_id: str, voice_settings: VoiceSettings | None = None) -> str:
        """Generate TTS audio via ElevenLabs API. Returns cache filename.
        Skips API call if already cached."""
        filename = _cache_key(text, voice_id, voice_settings)
        filepath = self.cache_dir / filename

        if filepath.exists() and filepath.stat().st_size > 0:
            logger.debug(f"TTS cache hit: {filename}")
            return filename

        vs = voice_settings or VoiceSettings()
        url = f"{ELEVENLABS_API_URL}/{voice_id}"
        headers = {
            "xi-api-key": self.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {
                "stability": vs.stability,
                "similarity_boost": vs.similarity_boost,
                "style": vs.style,
                "use_speaker_boost": vs.use_speaker_boost,
            },
            "speed": vs.speed,
        }

        session = await self._get_http_session()
        async with session.post(url, headers=headers, json=payload,
                                timeout=ELEVENLABS_REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                audio_data = await resp.read()
                filepath.write_bytes(audio_data)
                logger.info(f"TTS generated: {filename} ({len(audio_data)} bytes)")
                return filename
            else:
                body = await resp.text()
                logger.error(f"ElevenLabs API error {resp.status}: {body[:200]}")
                raise RuntimeError(f"ElevenLabs TTS failed: {resp.status}")

    async def generate_intro_music(self, theme_slug: str, prompt: str, variations: list[str] | None = None) -> str:
        """Generate intro music via ElevenLabs Sound Generation API.
        Uses a fixed filename per theme so it's only generated once ever."""
        filename = f"intro_music_{theme_slug}_30s.mp3"
        filepath = self.cache_dir / filename

        if filepath.exists() and filepath.stat().st_size > 0:
            logger.info(f"Intro music cache hit: {filename}")
            return filename

        # Add random variation so regeneration produces different results
        if not variations:
            variations = [
                "with building energy", "with a dramatic opening",
                "starting soft then building", "with punchy percussion",
            ]
        variation = random.choice(variations)
        varied_prompt = f"{prompt}, {variation}"
        logger.info(f"Music prompt variation: '{variation}'")

        headers = {
            "xi-api-key": self.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": varied_prompt,
            "duration_seconds": 30.0,
        }

        logger.info(f"Generating intro music for {theme_slug}...")
        session = await self._get_http_session()
        async with session.post(ELEVENLABS_SFX_URL, headers=headers, json=payload,
                                timeout=ELEVENLABS_REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                audio_data = await resp.read()
                filepath.write_bytes(audio_data)
                logger.info(f"Intro music generated: {filename} ({len(audio_data)} bytes)")
                return filename
            else:
                body = await resp.text()
                logger.error(f"ElevenLabs SFX error {resp.status}: {body[:200]}")
                return ""

    async def fade_out_speaker(self, speaker: str, start_volume: float):
        """Gradually fade out a speaker's volume."""
        for i in range(FADE_STEPS):
            vol = start_volume * (1 - (i + 1) / FADE_STEPS)
            await self.set_volume(speaker, max(vol, 0.0))
            await asyncio.sleep(FADE_STEP_TIME)
        # Stop playback
        await self.call_service("media_player", "media_stop", speaker)

    def _media_source_uri(self, filename: str) -> str:
        """Return the media-source URI for a file in HA's media library."""
        return f"media-source://media_source/local/mc_audio/{filename}"

    async def upload_to_ha(self, filename: str) -> str:
        """Upload an audio file to HA's media library.
        Returns the media-source:// URI for play_media."""
        if filename in self._ha_uploaded:
            return self._media_source_uri(filename)

        filepath = self.cache_dir / filename
        audio_data = filepath.read_bytes()

        upload_url = f"{self.ha_url}/api/media_source/local_source/upload"
        form = aiohttp.FormData()
        form.add_field("media_content_id", "media-source://media_source/local/mc_audio/.")
        form.add_field("file", audio_data,
                        filename=filename,
                        content_type="audio/mpeg")

        session = await self._get_http_session()
        async with session.post(upload_url, data=form,
                                headers={"Authorization": f"Bearer {self.ha_token}"},
                                timeout=HA_REQUEST_TIMEOUT) as resp:
            if resp.status in (200, 201):
                self._ha_uploaded.add(filename)
                uri = self._media_source_uri(filename)
                logger.info(f"Uploaded to HA media: {filename}")
                return uri
            else:
                body = await resp.text()
                logger.error(f"HA media upload failed {resp.status}: {body[:300]}")
                # Fallback: serve from our own server
                if self.server_url:
                    return f"{self.server_url}/audio/{filename}"
                raise RuntimeError(f"Failed to upload audio to HA: {resp.status}")

    async def cleanup_ha_media(self):
        """Delete all uploaded audio files from HA's media library."""
        if not self._ha_uploaded:
            return
        delete_url = f"{self.ha_url}/api/media_source/local_source/remove"
        headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }
        session = await self._get_http_session()
        for filename in list(self._ha_uploaded):
            media_id = self._media_source_uri(filename)
            try:
                async with session.post(delete_url, headers=headers,
                                        json={"media_content_id": media_id},
                                        timeout=HA_REQUEST_TIMEOUT) as resp:
                    if resp.status in (200, 201):
                        logger.debug(f"Deleted from HA media: {filename}")
                    else:
                        logger.warning(f"HA media delete failed for {filename}: {resp.status}")
            except Exception as e:
                logger.warning(f"HA media delete error for {filename}: {e}")
        logger.info(f"Cleaned up {len(self._ha_uploaded)} files from HA media library")
        self._ha_uploaded.clear()

    def _build_clip_list(self, theme: Theme, challenges: list[Challenge],
                         intro_text: str, outro_template: str):
        """Build the full list of clips needed and populate _announcement_options.
        Returns (critical_clips, remaining_clips) where critical = intro + first challenge.
        Each clip is a (text, voice_id, voice_settings) triple."""
        ann_vs = theme.announcer_voice_settings
        cel_vs = theme.celebration_voice_settings
        all_clips: list[tuple[str, str, VoiceSettings]] = []
        self._announcement_options: dict[str, list[str]] = {}

        # Intro
        all_clips.append((intro_text, theme.announcer_voice, ann_vs))

        # Per-challenge: build wrapped announcements
        for c in challenges:
            options = []
            wrapped = theme.wrap_announcement(c.announcement)
            options.append(wrapped)
            all_clips.append((wrapped, theme.announcer_voice, ann_vs))
            for funny in c.funny_announcements:
                wrapped_funny = theme.wrap_announcement(funny)
                options.append(wrapped_funny)
                all_clips.append((wrapped_funny, theme.announcer_voice, ann_vs))
            self._announcement_options[c.name] = options
            all_clips.append((theme.wrap_hint(c.hint), theme.announcer_voice, ann_vs))

        # Timeout phrases
        for phrase in theme.timeout_phrases:
            all_clips.append((phrase, theme.announcer_voice, ann_vs))

        # Success prefix variants (precache a few common combos)
        for c in challenges:
            spoken_times = ["5", "10", "15", "20", "30"]
            for t in spoken_times:
                spoken = _seconds_to_words(t)
                success_msg = c.success_message.format(time=spoken)
                all_clips.append((theme.wrap_success(success_msg), theme.celebration_voice, cel_vs))

        # Outro variants
        for completed in range(0, len(challenges) + 1):
            for total in ["20", "30", "45", "60", "90", "120"]:
                spoken_total = _seconds_to_words(total)
                all_clips.append((
                    outro_template.format(total_time=spoken_total, rounds=completed),
                    theme.celebration_voice,
                    cel_vs,
                ))

        # Deduplicate
        seen = set()
        unique_clips = []
        for text, voice, vs in all_clips:
            key = _cache_key(text, voice, vs)
            if key not in seen:
                seen.add(key)
                unique_clips.append((text, voice, vs))

        # Split: intro + first challenge clips are critical
        critical_keys = {_cache_key(intro_text, theme.announcer_voice, ann_vs)}
        if challenges:
            c = challenges[0]
            for opt in self._announcement_options.get(c.name, []):
                critical_keys.add(_cache_key(opt, theme.announcer_voice, ann_vs))
            critical_keys.add(_cache_key(theme.wrap_hint(c.hint), theme.announcer_voice, ann_vs))

        critical = [(t, v, vs) for t, v, vs in unique_clips if _cache_key(t, v, vs) in critical_keys]
        remaining = [(t, v, vs) for t, v, vs in unique_clips if _cache_key(t, v, vs) not in critical_keys]

        return critical, remaining

    async def _generate_and_upload(self, clips: list[tuple[str, str, VoiceSettings]], label: str = ""):
        """Generate TTS and upload to HA for a list of (text, voice_id, voice_settings) clips."""
        to_generate = []
        for text, voice, vs in clips:
            filename = _cache_key(text, voice, vs)
            filepath = self.cache_dir / filename
            if not filepath.exists() or filepath.stat().st_size == 0:
                to_generate.append((text, voice, vs))

        if label:
            logger.info(f"Audio {label}: {len(clips)} clips, {len(to_generate)} to generate")

        sem = asyncio.Semaphore(3)

        async def gen(text, voice, vs):
            async with sem:
                await self.generate_tts(text, voice, vs)

        if to_generate:
            await asyncio.gather(*[gen(t, v, vs) for t, v, vs in to_generate])

        # Upload to HA
        upload_sem = asyncio.Semaphore(5)

        async def upload(fn):
            async with upload_sem:
                try:
                    await self.upload_to_ha(fn)
                except Exception as e:
                    logger.error(f"Upload failed for {fn}: {e}")

        all_filenames = [_cache_key(t, v, vs) for t, v, vs in clips]
        await asyncio.gather(*[upload(fn) for fn in all_filenames])

    async def precache_critical_audio(self, theme: Theme, challenges: list[Challenge],
                                      intro_text: str, outro_template: str):
        """Generate intro + first challenge audio (blocks), then kick off
        background task for the rest. Returns immediately after critical audio is ready."""
        critical, remaining = self._build_clip_list(theme, challenges, intro_text, outro_template)

        await self.broadcast({
            "type": "precaching",
            "message": f"Preparing audio ({len(critical)} critical, {len(remaining)} background)...",
        })

        # Generate critical clips synchronously — game can't start without these
        await self._generate_and_upload(critical, label="critical")
        await self.broadcast({"type": "precaching_done"})

        # Generate remaining clips in background — game continues while this runs
        if remaining:
            self._bg_cache_task = asyncio.create_task(self._background_cache(remaining))
        else:
            self._bg_cache_task = None

    async def _background_cache(self, clips: list[tuple[str, str, VoiceSettings]]):
        """Background task to generate and upload remaining audio clips."""
        try:
            await self._generate_and_upload(clips, label="background")
            logger.info("Background audio cache complete")
        except Exception as e:
            logger.error(f"Background cache error: {e}")

    async def play_on_appletv(self, audio_path: str | None, **kwargs):
        """Broadcast audio URL via WebSocket for tvOS app to play.
        The tvOS app renders visuals natively — we just send it audio."""
        if not audio_path:
            return

        filename = Path(audio_path).name
        audio_url = f"{self.server_url}/audio/{filename}"
        duration = _get_mp3_duration(audio_path)

        # Broadcast audio event — tvOS app picks this up and plays it
        await self.broadcast({
            "type": "atv_play_audio",
            "audio_url": audio_url,
            "duration": duration,
        })

        logger.info(f"ATV audio broadcast: {filename} ({duration:.1f}s)")
        await asyncio.sleep(duration)

    def request_advance(self):
        """Signal inter-round advancement from the dashboard."""
        self.advance_event.set()

    async def play_cached_audio(self, speaker: str, text: str, voice_id: str, voice_settings: VoiceSettings | None = None):
        """Play cached TTS audio on a speaker (Sonos or Apple TV)."""
        resolved = self._resolve_speaker(speaker)

        # Generate/fetch audio
        filename = await self.generate_tts(text, voice_id, voice_settings)
        filepath = self.cache_dir / filename

        # Apple TV path: broadcast audio URL for tvOS app
        if resolved == "appletv":
            await self.play_on_appletv(audio_path=str(filepath))
            return

        # Sonos path: upload to HA and play
        media_url = await self.upload_to_ha(filename)

        await self.set_volume(resolved, self.speaker_volume)

        # Play via HA media_player.play_media
        await self.call_service(
            "media_player", "play_media",
            resolved,
            media_content_id=media_url,
            media_content_type="music",
            announce=True,
        )

        # Wait for actual audio duration
        duration = _get_mp3_duration(filepath)
        logger.info(f"Playing on {resolved}: {filename} ({duration:.1f}s)")
        await asyncio.sleep(duration)

    # --- Home Assistant ---

    async def fetch_all_states(self):
        """Fetch all entity states via REST API."""
        url = f"{self.ha_url}/api/states"
        headers = {"Authorization": f"Bearer {self.ha_token}"}
        session = await self._get_http_session()
        async with session.get(url, headers=headers, timeout=HA_REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                states = await resp.json()
                self.state_cache = {
                    s["entity_id"]: s["state"] for s in states
                }
                logger.info(f"Cached {len(self.state_cache)} entity states")
            else:
                logger.error(f"Failed to fetch states: {resp.status}")
                raise RuntimeError(f"Failed to fetch HA states: {resp.status}")

    async def connect_ws(self):
        """Connect to Home Assistant WebSocket and authenticate."""
        # Close any existing connection first
        await self.disconnect_ws()

        self.ws_session = aiohttp.ClientSession()
        self.ws = await self.ws_session.ws_connect(self.ha_ws_url)

        msg = await self.ws.receive_json()
        logger.info(f"WS: {msg.get('type')}")

        await self.ws.send_json({
            "type": "auth",
            "access_token": self.ha_token,
        })
        msg = await self.ws.receive_json()
        if msg.get("type") != "auth_ok":
            raise ConnectionError(f"HA WS auth failed: {msg}")
        logger.info("WS authenticated")

        self.ws_msg_id += 1
        await self.ws.send_json({
            "id": self.ws_msg_id,
            "type": "subscribe_events",
            "event_type": "state_changed",
        })
        msg = await self.ws.receive_json()
        logger.info(f"Subscribed to state_changed: {msg}")

    async def reconnect_ws(self) -> bool:
        """Attempt to reconnect the HA WebSocket. Returns True on success."""
        for attempt in range(1, MAX_WS_RECONNECT_ATTEMPTS + 1):
            try:
                logger.warning(f"WS reconnect attempt {attempt}/{MAX_WS_RECONNECT_ATTEMPTS}")
                await self.connect_ws()
                logger.info("WS reconnected successfully")
                return True
            except Exception as e:
                logger.error(f"WS reconnect attempt {attempt} failed: {e}")
                await asyncio.sleep(2)
        logger.error("WS reconnect failed after all attempts")
        return False

    async def disconnect_ws(self):
        """Disconnect WebSocket."""
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.ws_session and not self.ws_session.closed:
            await self.ws_session.close()
        self.ws = None
        self.ws_session = None

    async def call_service(self, domain: str, service: str, entity_id: str, **kwargs):
        """Call a Home Assistant service via REST API."""
        url = f"{self.ha_url}/api/services/{domain}/{service}"
        headers = {
            "Authorization": f"Bearer {self.ha_token}",
            "Content-Type": "application/json",
        }
        data = {"entity_id": entity_id, **kwargs}
        session = await self._get_http_session()
        async with session.post(url, headers=headers, json=data,
                                timeout=HA_REQUEST_TIMEOUT) as resp:
            body = await resp.text()
            if resp.status not in (200, 201):
                logger.error(f"Service call failed: {domain}.{service} -> {resp.status}: {body}")
            else:
                logger.info(f"Service called: {domain}.{service} on {entity_id}")

    async def set_volume(self, speaker: str, volume: float):
        """Set speaker volume."""
        await self.call_service("media_player", "volume_set", speaker, volume_level=volume)

    async def drain_ws_events(self, max_iterations: int = 20, timeout: float = 0.25):
        """Drain WebSocket events, updating state cache."""
        for _ in range(max_iterations):
            try:
                msg = await asyncio.wait_for(self.ws.receive_json(), timeout=timeout)
                if msg.get("type") == "event":
                    event_data = msg.get("event", {}).get("data", {})
                    entity_id = event_data.get("entity_id")
                    new_state = event_data.get("new_state", {})
                    if entity_id and new_state:
                        self.state_cache[entity_id] = new_state.get("state", "unknown")
            except asyncio.TimeoutError:
                break
            except Exception:
                break

    async def pre_setup_challenge(self, challenge: Challenge):
        """Execute pre-setup steps for a challenge."""
        for step in challenge.pre_setup:
            logger.info(f"Pre-setup: {step.domain}.{step.service} on {step.entity_id}")
            await self.call_service(step.domain, step.service, step.entity_id)

        await self.drain_ws_events()

        for step in challenge.pre_setup:
            expected = "off" if "turn_off" in step.service else "on"
            if self.state_cache.get(step.entity_id) != expected:
                logger.warning(f"Pre-setup not confirmed for {step.entity_id}, force-updating cache")
                self.state_cache[step.entity_id] = expected

    def select_challenges(self, difficulty: str, num_rounds: int, floors: list[str] | None = None) -> list[Challenge]:
        """Select and order challenges based on difficulty and floor filter from the database."""
        all_challenges = self.challenge_db.to_challenge_objects()

        if difficulty == "easy":
            pool = [c for c in all_challenges if c.difficulty == Difficulty.EASY]
        elif difficulty == "hard":
            pool = [c for c in all_challenges if c.difficulty in (Difficulty.MEDIUM, Difficulty.HARD)]
        else:  # mixed
            pool = list(all_challenges)

        # Floor filtering: keep challenges on selected floors or unassigned (empty floor)
        if floors:
            floor_set = set(floors)
            pool = [c for c in pool if not c.floor or c.floor in floor_set]

        random.shuffle(pool)
        selected = pool[:num_rounds]

        if difficulty == "mixed":
            order = {Difficulty.EASY: 0, Difficulty.MEDIUM: 1, Difficulty.HARD: 2}
            selected.sort(key=lambda c: order[c.difficulty])

        return selected

    async def _ws_receive_or_reconnect(self, timeout: float = 1.0):
        """Receive a WS message, reconnecting if the connection is broken.
        Returns the message dict, or None on timeout."""
        try:
            msg = await asyncio.wait_for(self.ws.receive_json(), timeout=timeout)
            return msg
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            logger.error(f"WS error: {e}, attempting reconnect...")
            if await self.reconnect_ws():
                return None  # reconnected, but no message this cycle
            raise RuntimeError("HA WebSocket connection lost and reconnect failed")

    async def monitor_round(self, challenge: Challenge) -> dict:
        """Monitor WebSocket for challenge completion."""
        targets_remaining = {t.entity_id: t.target_state for t in challenge.targets}
        targets_completed = set()

        needs_change_event: set[str] = set()
        pre_setup_entities = {s.entity_id for s in challenge.pre_setup}
        for target in challenge.targets:
            if target.entity_id not in pre_setup_entities:
                current = self.state_cache.get(target.entity_id)
                if current == target.target_state:
                    needs_change_event.add(target.entity_id)
                    logger.info(f"{target.entity_id} already in target state '{target.target_state}', requiring change event")

        left_target_state: set[str] = set()
        start_time = time.time()
        hint_sent = False
        elapsed = 0

        while elapsed < ROUND_TIMEOUT:
            if self.skip_requested:
                self.skip_requested = False
                return {"status": "skipped", "time": round(elapsed, 1)}

            if self.stop_requested:
                return {"status": "stopped", "time": round(elapsed, 1)}

            elapsed = time.time() - start_time

            if not hint_sent and elapsed >= HINT_TIME:
                hint_sent = True
                theme = self._current_theme
                hint_text = theme.wrap_hint(challenge.hint)
                await self.play_cached_audio(
                    self.hub_speaker,
                    hint_text,
                    theme.announcer_voice,
                    theme.announcer_voice_settings,
                )

            await self.broadcast({
                "type": "timer_tick",
                "elapsed": round(elapsed, 1),
                "timeout": ROUND_TIMEOUT,
            })

            msg = await self._ws_receive_or_reconnect(timeout=1.0)
            if msg is None:
                continue

            if msg.get("type") == "event":
                event_data = msg.get("event", {}).get("data", {})
                entity_id = event_data.get("entity_id")
                new_state_obj = event_data.get("new_state", {})
                new_state = new_state_obj.get("state", "") if new_state_obj else ""

                if entity_id:
                    self.state_cache[entity_id] = new_state

                    if entity_id in targets_remaining:
                        target_state = targets_remaining[entity_id]

                        if entity_id in needs_change_event:
                            if new_state != target_state:
                                left_target_state.add(entity_id)
                            elif new_state == target_state and entity_id in left_target_state:
                                targets_completed.add(entity_id)
                                del targets_remaining[entity_id]
                        elif new_state == target_state:
                            targets_completed.add(entity_id)
                            del targets_remaining[entity_id]

                        await self.broadcast({
                            "type": "target_update",
                            "targets": [
                                {"entity_id": t.entity_id, "completed": t.entity_id in targets_completed}
                                for t in challenge.targets
                            ],
                        })

                        if not targets_remaining:
                            completion_time = round(time.time() - start_time, 1)
                            return {"status": "completed", "time": completion_time}

        return {"status": "timeout", "time": ROUND_TIMEOUT}

    async def run_game(self, theme_slug: str, num_rounds: int, difficulty: str, floors: list[str] | None = None, challenge_ids: list[str] | None = None):
        """Run the full game loop."""
        self.running = True
        self.stop_requested = False
        self.skip_requested = False
        self.results = []
        self.current_round = 0
        self.total_rounds = num_rounds
        self._ha_uploaded.clear()
        self.advance_event.clear()

        theme = ALL_THEMES.get(theme_slug, ALL_THEMES["mission_control"])
        self._current_theme = theme

        if self.test_mode:
            logger.info(f"TEST MODE: All audio routed to {self.test_speaker}")
        if self.appletv_mode:
            logger.info("APPLE TV MODE: Hub audio routed to Apple TV")

        await self.broadcast({"type": "game_starting", "theme": theme.name, "theme_slug": theme.slug, "rounds": num_rounds})

        try:
            if self.appletv_mode:
                logger.info("APPLE TV MODE: Hub audio broadcast via WebSocket for tvOS app")
                await self.broadcast({"type": "atv_connected"})

            # Fetch all states
            await self.fetch_all_states()

            # Select challenges — use explicit IDs if provided (from review flow)
            if challenge_ids:
                all_challenges = self.challenge_db.to_challenge_objects()
                # Build lookup by matching DB entries
                all_db = self.challenge_db.load()
                id_to_name = {c["id"]: c["name"] for c in all_db}
                name_lookup = {c.name: c for c in all_challenges}
                challenges = []
                for cid in challenge_ids:
                    name = id_to_name.get(cid)
                    if name and name in name_lookup:
                        challenges.append(name_lookup[name])
            else:
                challenges = self.select_challenges(difficulty, num_rounds, floors=floors)
            self.total_rounds = len(challenges)

            # Save original states
            for c in challenges:
                for t in c.targets:
                    if t.entity_id not in self.original_states:
                        self.original_states[t.entity_id] = self.state_cache.get(t.entity_id, "unknown")
                for s in c.pre_setup:
                    if s.entity_id not in self.original_states:
                        self.original_states[s.entity_id] = self.state_cache.get(s.entity_id, "unknown")

            # Pick intro and outro up front so we can precache them
            intro_text = theme.pick_intro()
            outro_template = theme.pick_outro()
            hub = self.hub_speaker  # unresolved — play_cached_audio resolves it
            hub_resolved = self._resolve_speaker(hub)

            # Start background image precache ASAP — room images are prioritized first
            self._bg_image_task = asyncio.create_task(self._precache_images(theme, challenges))

            # Generate intro music (only first time per theme, then cached forever)
            music_file = ""
            if theme.intro_music_prompt:
                music_file = await self.generate_intro_music(theme.slug, theme.intro_music_prompt, theme.intro_music_variations)

            # Use pre-cached intro image if available (never block on generation)
            intro_image_url = self._get_cached_image_url(theme.intro_scene_prompt) if theme.intro_scene_prompt else None
            if intro_image_url:
                await self.broadcast({
                    "type": "game_starting",
                    "theme": theme.name,
                    "theme_slug": theme.slug,
                    "rounds": num_rounds,
                    "intro_image_url": intro_image_url,
                })

            # Start playing intro music while we precache (non-blocking)
            music_start = time.time()
            if music_file:
                if hub_resolved == "appletv":
                    filename = Path(music_file).name
                    audio_url = f"{self.server_url}/audio/{filename}"
                    await self.broadcast({
                        "type": "atv_play_audio",
                        "audio_url": audio_url,
                    })
                    logger.info(f"ATV intro music broadcast (non-blocking)")
                else:
                    music_url = await self.upload_to_ha(music_file)
                    volume = self.speaker_volume * INTRO_MUSIC_VOLUME_RATIO
                    await self.set_volume(hub_resolved, volume)
                    await self.call_service(
                        "media_player", "play_media", hub_resolved,
                        media_content_id=music_url,
                        media_content_type="music",
                    )
                    logger.info(f"Intro music playing on {hub_resolved}")

            # Pre-cache critical audio (intro + first challenge), rest continues in background
            await self.precache_critical_audio(theme, challenges, intro_text, outro_template)

            # Ensure at least 15s of intro music plays before moving on
            if music_file:
                elapsed = time.time() - music_start
                remaining = 15.0 - elapsed
                if remaining > 0:
                    logger.info(f"Waiting {remaining:.1f}s for intro music minimum")
                    await asyncio.sleep(remaining)

            # Connect WS
            await self.connect_ws()

            # Fade out music
            if music_file:
                if hub_resolved == "appletv":
                    await self.broadcast({"type": "atv_fade_out"})
                    await asyncio.sleep(FADE_STEPS * FADE_STEP_TIME + 0.5)
                else:
                    volume = self.speaker_volume * INTRO_MUSIC_VOLUME_RATIO
                    await self.fade_out_speaker(hub_resolved, volume)
                    await asyncio.sleep(0.5)

            # Intro TTS
            await self.play_cached_audio(hub, intro_text, theme.announcer_voice, theme.announcer_voice_settings)

            await self.broadcast({"type": "game_started", "total_rounds": len(challenges)})

            total_time = 0
            for i, challenge in enumerate(challenges):
                if self.stop_requested:
                    break

                self.current_round = i + 1

                # Look up pre-cached scene image (background task generates these, never block here)
                scene_image_url = None
                if theme.mission_scene_template:
                    scene_prompt = theme.mission_scene_template.format(room=challenge.room)
                    scene_image_url = self._get_cached_image_url(scene_prompt)

                await self.broadcast({
                    "type": "round_starting",
                    "round": self.current_round,
                    "total_rounds": len(challenges),
                    "challenge": {
                        "name": challenge.name,
                        "room": challenge.room,
                        "difficulty": challenge.difficulty.value,
                        "targets": [{"entity_id": t.entity_id, "target_state": t.target_state} for t in challenge.targets],
                        "multi_target": challenge.multi_target,
                    },
                    "scene_image_url": scene_image_url,
                })

                # Pre-setup
                if challenge.pre_setup:
                    await self.pre_setup_challenge(challenge)

                # Pick announcement from precached options (first is standard, rest are funny)
                options = self._announcement_options.get(challenge.name, [])
                if len(options) > 1 and random.random() < 0.33:
                    announcement = random.choice(options[1:])
                elif options:
                    announcement = options[0]
                else:
                    announcement = theme.wrap_announcement(challenge.announcement)

                # In Apple TV mode, broadcast audio URL with round_starting for tvOS app
                if self.appletv_mode and self._resolve_speaker(self.hub_speaker) == "appletv":
                    filename = await self.generate_tts(announcement, theme.announcer_voice, theme.announcer_voice_settings)
                    audio_url = f"{self.server_url}/audio/{filename}"
                    audio_path = str(self.cache_dir / filename)
                    duration = _get_mp3_duration(audio_path)

                    await self.broadcast({
                        "type": "atv_play_audio",
                        "audio_url": audio_url,
                        "duration": duration,
                    })
                    logger.info(f"ATV announcement: {filename} ({duration:.1f}s)")
                    await asyncio.sleep(duration)
                else:
                    await self.play_cached_audio(
                        self.hub_speaker,
                        announcement,
                        theme.announcer_voice,
                        theme.announcer_voice_settings,
                    )

                # Monitor
                result = await self.monitor_round(challenge)
                result["round"] = self.current_round
                result["challenge_name"] = challenge.name

                if result["status"] == "completed":
                    total_time += result["time"]
                    spoken_time = _seconds_to_words(str(result["time"]))
                    success_text = theme.wrap_success(
                        challenge.success_message.format(time=spoken_time)
                    )
                    await self.play_cached_audio(
                        challenge.success_speaker,
                        success_text,
                        theme.celebration_voice,
                        theme.celebration_voice_settings,
                    )
                    await self.broadcast({"type": "round_complete", **result})
                elif result["status"] == "skipped":
                    await self.broadcast({"type": "round_skipped", **result})
                elif result["status"] == "timeout":
                    total_time += result["time"]
                    timeout_text = theme.pick_timeout()
                    await self.play_cached_audio(
                        self.hub_speaker,
                        timeout_text,
                        theme.announcer_voice,
                        theme.announcer_voice_settings,
                    )
                    await self.broadcast({"type": "round_complete", **result})
                elif result["status"] == "stopped":
                    self.results.append(result)
                    break

                self.results.append(result)

                # Apple TV mode: wait for advance between rounds
                if self.appletv_mode and i < len(challenges) - 1 and not self.stop_requested:
                    self.advance_event.clear()
                    transition_image_url = self._get_cached_image_url(theme.transition_prompt) if theme.transition_prompt else None
                    await self.broadcast({"type": "atv_waiting_for_advance", "transition_image_url": transition_image_url})
                    logger.info("Waiting for dashboard advance...")

                    # Wait for advance or stop
                    while not self.advance_event.is_set() and not self.stop_requested:
                        await asyncio.sleep(0.5)

                    if self.stop_requested:
                        break

            # Ensure background cache is done before finale (outro needs its audio)
            if hasattr(self, '_bg_cache_task') and self._bg_cache_task:
                await self._bg_cache_task
                self._bg_cache_task = None

            # Finale
            if not self.stop_requested:
                completed_count = sum(1 for r in self.results if r["status"] == "completed")
                total_time_rounded = round(total_time, 1)

                # Notify tvOS to show finale screen while outro TTS plays
                outro_image_url = self._get_cached_image_url(theme.outro_scene_prompt) if theme.outro_scene_prompt else None
                await self.broadcast({
                    "type": "finale",
                    "completed": completed_count,
                    "total_rounds": len(challenges),
                    "outro_image_url": outro_image_url,
                })

                spoken_total = _seconds_to_words(str(total_time_rounded))
                outro = outro_template.format(
                    total_time=spoken_total,
                    rounds=completed_count,
                )
                outro_resolved = self._resolve_speaker(self.hub_speaker)
                if outro_resolved != "appletv":
                    await self.set_volume(outro_resolved, self.speaker_volume)
                await self.play_cached_audio(self.hub_speaker, outro, theme.celebration_voice, theme.celebration_voice_settings)

                await self.broadcast({
                    "type": "game_finished",
                    "results": self.results,
                    "total_time": total_time_rounded,
                    "completed": completed_count,
                    "total_rounds": len(challenges),
                    "outro_image_url": outro_image_url,
                })
            else:
                await self.broadcast({
                    "type": "game_stopped",
                    "results": self.results,
                })

        except Exception as e:
            logger.exception(f"Game error: {e}")
            await self.broadcast({"type": "error", "message": str(e)})
        finally:
            if hasattr(self, '_bg_cache_task') and self._bg_cache_task:
                self._bg_cache_task.cancel()
                self._bg_cache_task = None
            if hasattr(self, '_bg_image_task') and self._bg_image_task:
                self._bg_image_task.cancel()
                self._bg_image_task = None
            await self.restore_states()
            await self.cleanup_ha_media()
            await self.disconnect_ws()
            await self._close_http_session()
            self.running = False

    async def restore_states(self):
        """Restore all modified entities to original states."""
        logger.info("Restoring entity states...")
        try:
            await self.fetch_all_states()
        except Exception as e:
            logger.error(f"Failed to refresh states for restore: {e}")

        for entity_id, original_state in self.original_states.items():
            current = self.state_cache.get(entity_id)
            if current != original_state and original_state != "unknown":
                domain = entity_id.split(".")[0]
                if original_state == "on":
                    await self.call_service(domain, "turn_on", entity_id)
                elif original_state == "off":
                    await self.call_service(domain, "turn_off", entity_id)
                logger.info(f"Restored {entity_id}: {current} -> {original_state}")

        self.original_states.clear()

    def get_state(self) -> dict:
        """Get current game state for API."""
        completed = sum(1 for r in self.results if r["status"] == "completed")
        total_time = sum(r["time"] for r in self.results if r["status"] == "completed")
        return {
            "running": self.running,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "results": self.results,
            "completed_count": completed,
            "total_time": round(total_time, 1),
        }

    def request_skip(self):
        self.skip_requested = True

    def request_stop(self):
        self.stop_requested = True
