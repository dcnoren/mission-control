"""FastAPI server for Mission Control."""
import asyncio
import collections
import json
import logging
import os
import random
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from challenge_db import ChallengeDB
from challenge_gen import ChallengeGenerator
from engine import GameEngine, _ha_url_to_ws
from image_gen import ImageGenerator
from themes import ALL_THEMES
import copy

# Snapshot original theme phrases so reset can restore them
_THEME_DEFAULTS = {
    slug: {
        "intro_texts": copy.deepcopy(theme.intro_texts),
        "outro_texts": copy.deepcopy(theme.outro_texts),
        "announcement_prefixes": copy.deepcopy(theme.announcement_prefixes),
        "success_prefixes": copy.deepcopy(theme.success_prefixes),
        "hint_prefixes": copy.deepcopy(theme.hint_prefixes),
        "timeout_phrases": copy.deepcopy(theme.timeout_phrases),
    }
    for slug, theme in ALL_THEMES.items()
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("mission_control.server")

DATA_DIR = Path("/app/data")
CONFIG_FILE = DATA_DIR / "config.json"
CACHE_DIR = DATA_DIR / "cache"
VIDEO_DIR = CACHE_DIR / "video"
IMAGE_DIR = CACHE_DIR / "images"
LOG_DIR = DATA_DIR / "logs"

# Ensure dirs exist before StaticFiles mounts
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Connected WebSocket clients
ws_clients: set[WebSocket] = set()


# --- Debug Log Handler ---

class _WebSocketLogHandler(logging.Handler):
    """Buffers log records for WS broadcast and writes to file when enabled."""

    def __init__(self, log_dir: Path, max_buffer: int = 500):
        super().__init__()
        self.log_dir = log_dir
        self.log_file = None
        self.max_buffer = max_buffer
        self.pending = collections.deque()  # drained by broadcast loop
        self.history = collections.deque(maxlen=max_buffer)  # kept for API
        self._enabled = False

    def enable(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = open(self.log_dir / "debug.log", "a")
        self._enabled = True

    def disable(self):
        self._enabled = False
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def emit(self, record):
        if not self._enabled:
            return
        line = self.format(record)
        self.pending.append(line)
        self.history.append(line)
        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()


_ws_log_handler = _WebSocketLogHandler(LOG_DIR)
_ws_log_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
logging.getLogger("mission_control").addHandler(_ws_log_handler)


def set_debug_logging(enabled: bool):
    """Toggle debug logging on/off."""
    mc_logger = logging.getLogger("mission_control")
    if enabled:
        mc_logger.setLevel(logging.DEBUG)
        _ws_log_handler.enable()
        logger.info("Debug logging enabled")
    else:
        logger.info("Debug logging disabled")
        mc_logger.setLevel(logging.INFO)
        _ws_log_handler.disable()

# Game engine (initialized on startup)
engine: GameEngine = None

# Challenge database and pending suggestions
challenge_db = ChallengeDB(str(DATA_DIR / "challenges.db"))
pending_suggestions: dict[str, dict] = {}  # temp_id -> challenge_dict




def load_config() -> dict:
    """Load persisted config from disk."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    return {}


def save_config(config: dict):
    """Save config to disk atomically via temp file + rename."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, str(CONFIG_FILE))
        logger.info("Config saved")
    except Exception:
        os.unlink(tmp_path)
        raise


async def broadcast(data: dict):
    """Broadcast a message to all connected WebSocket clients."""
    global ws_clients
    message = json.dumps(data)
    disconnected = set()
    for ws in list(ws_clients):  # iterate a copy
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    ws_clients -= disconnected


async def _log_broadcast_loop():
    """Drain log buffer and broadcast to WS clients at ~4Hz."""
    while True:
        await asyncio.sleep(0.25)
        if not _ws_log_handler._enabled or not _ws_log_handler.pending:
            continue
        lines = []
        while _ws_log_handler.pending:
            lines.append(_ws_log_handler.pending.popleft())
        if lines:
            await broadcast({"type": "log_lines", "lines": lines})


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine

    # Load persisted config, fall back to env vars
    config = load_config()
    ha_url = config.get("ha_url") or os.environ.get("HA_URL", "http://homeassistant.local:8123")
    ha_token = config.get("ha_token") or os.environ.get("HA_TOKEN", "")
    gemini_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    server_url = config.get("server_url") or os.environ.get("SERVER_URL", "")

    # Persist env var values into config so the UI shows them as configured
    needs_save = False
    for key, val in [
        ("ha_url", ha_url),
        ("ha_token", ha_token),
        ("gemini_api_key", gemini_key),
        ("server_url", server_url),
    ]:
        if val and not config.get(key):
            config[key] = val
            needs_save = True
    if needs_save:
        save_config(config)

    # Clean up old JSON-based challenge/blacklist files (migrated to SQLite)
    for old_file in ["challenges.json", "entity_blacklist.json"]:
        old_path = DATA_DIR / old_file
        if old_path.exists():
            old_path.unlink()
            logger.info(f"Removed legacy file: {old_file}")

    engine = GameEngine(
        ha_url=ha_url,
        ha_token=ha_token,
        gemini_api_key=gemini_key,
        broadcast=broadcast,
        cache_dir=str(CACHE_DIR),
        server_url=server_url,
    )

    engine.speaker_volume = config.get("speaker_volume", 0.40)

    _apply_phrase_overrides()

    # Restore debug logging state
    if config.get("debug_logging"):
        set_debug_logging(True)

    # Start log broadcast loop
    log_task = asyncio.create_task(_log_broadcast_loop())

    # Log cache status on startup
    cached_files = list([f for f in CACHE_DIR.iterdir() if f.suffix in (".mp3", ".wav")])
    logger.info(f"Mission Control ready. HA: {ha_url} | Audio cache: {len(cached_files)} files")
    yield
    log_task.cancel()
    if engine.running:
        engine.request_stop()


app = FastAPI(title="Mission Control", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/audio", StaticFiles(directory=str(CACHE_DIR)), name="audio")
app.mount("/video", StaticFiles(directory=str(VIDEO_DIR)), name="video")
app.mount("/images", StaticFiles(directory=str(IMAGE_DIR)), name="images")


class StartRequest(BaseModel):
    theme: str = "mission_control"
    rounds: int = 5
    difficulty: str = "mixed"
    ha_url: str | None = None
    hub_speaker: str | None = None
    appletv_mode: bool = False
    local_mode: bool = False
    floors: list[str] | None = None
    challenge_ids: list[str] | None = None


class ConfigRequest(BaseModel):
    ha_url: str | None = None
    ha_token: str | None = None
    gemini_api_key: str | None = None
    hub_speaker: str | None = None
    server_url: str | None = None
    speaker_volume: float | None = None


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html") as f:
        return HTMLResponse(f.read())


@app.get("/api/themes")
async def get_themes():
    return {
        slug: {"name": t.name, "slug": t.slug}
        for slug, t in ALL_THEMES.items()
    }


@app.get("/api/state")
async def get_state():
    return engine.get_state()


@app.get("/api/config")
async def get_config():
    """Return saved config (masks secrets to just show if set)."""
    config = load_config()
    cached_files = list([f for f in CACHE_DIR.iterdir() if f.suffix in (".mp3", ".wav")])
    return {
        "ha_url": config.get("ha_url", ""),
        "ha_token_set": bool(config.get("ha_token") or os.environ.get("HA_TOKEN")),
        "gemini_api_key_set": bool(config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")),
        "hub_speaker": config.get("hub_speaker", ""),
        "server_url": config.get("server_url", ""),
        "cached_audio_files": len(cached_files),
        "allowed_speakers": config.get("allowed_speakers", []),
        "floors": config.get("floors", []),
        "speaker_volume": config.get("speaker_volume", 0.40),
        "debug_logging": config.get("debug_logging", False),
    }


@app.post("/api/config")
async def update_config(req: ConfigRequest):
    """Save config to persistent storage and update engine."""
    if engine.running:
        return JSONResponse({"error": "Cannot update config while game is running"}, status_code=409)

    config = load_config()

    if req.ha_url is not None:
        config["ha_url"] = req.ha_url
        engine.update_ha_url(req.ha_url)

    if req.ha_token is not None:
        config["ha_token"] = req.ha_token
        engine.ha_token = req.ha_token

    if req.gemini_api_key is not None:
        config["gemini_api_key"] = req.gemini_api_key
        engine.gemini_api_key = req.gemini_api_key

    if req.hub_speaker is not None:
        config["hub_speaker"] = req.hub_speaker
        engine.hub_speaker = req.hub_speaker

    if req.server_url is not None:
        config["server_url"] = req.server_url
        engine.server_url = req.server_url.rstrip("/")

    if req.speaker_volume is not None:
        vol = max(0.0, min(1.0, req.speaker_volume))
        config["speaker_volume"] = vol
        engine.speaker_volume = vol

    save_config(config)
    return {"status": "saved"}


class DebugLoggingRequest(BaseModel):
    enabled: bool


@app.post("/api/debug/logging")
async def toggle_debug_logging(req: DebugLoggingRequest):
    """Toggle debug logging on/off. Can be used while game is running."""
    config = load_config()
    config["debug_logging"] = req.enabled
    save_config(config)
    set_debug_logging(req.enabled)
    return {"status": "ok", "debug_logging": req.enabled}


@app.get("/api/debug/logs")
async def get_recent_logs():
    """Return recent debug log lines from the buffer."""
    return {"lines": list(_ws_log_handler.history)}


@app.get("/api/debug/entities")
async def debug_entities():
    """Debug: show TTS and media_player entities from cache."""
    await engine.fetch_all_states()
    tts = {k: v for k, v in engine.state_cache.items() if k.startswith("tts.")}
    speakers = {k: v for k, v in engine.state_cache.items() if k.startswith("media_player.") and "sonos" in k.lower()}
    return {"tts_entities": tts, "sonos_speakers": speakers}


class AllowedSpeakersRequest(BaseModel):
    allowed_speakers: list[dict]  # [{entity_id, friendly_name, area}]


class FloorsRequest(BaseModel):
    floors: list[dict]  # [{name, areas: []}]


@app.post("/api/floors")
async def save_floors(req: FloorsRequest):
    """Save floor definitions to config."""
    config = load_config()
    config["floors"] = req.floors
    save_config(config)
    return {"status": "saved", "count": len(req.floors)}


@app.post("/api/speakers/save")
async def save_allowed_speakers(req: AllowedSpeakersRequest):
    """Save the list of allowed speakers to config."""
    config = load_config()
    config["allowed_speakers"] = req.allowed_speakers
    save_config(config)
    return {"status": "saved", "count": len(req.allowed_speakers)}


@app.get("/api/debug/cache")
async def debug_cache():
    """Debug: list cached audio files."""
    files = sorted([f for f in CACHE_DIR.iterdir() if f.suffix in (".mp3", ".wav")])
    return {
        "count": len(files),
        "files": [{"name": f.name, "size": f.stat().st_size} for f in files[:50]],
    }


@app.delete("/api/cache/tts")
async def clear_tts_cache():
    """Delete all cached TTS audio files (excludes intro music)."""
    if engine.running:
        return JSONResponse({"error": "Cannot clear cache while game is running"}, status_code=409)
    deleted = 0
    for f in [f for f in CACHE_DIR.iterdir() if f.suffix in (".mp3", ".wav")]:
        if not f.name.startswith("intro_music_"):
            f.unlink()
            deleted += 1
    return {"status": "cleared", "deleted": deleted}


@app.delete("/api/cache/all")
async def clear_all_cache():
    """Delete all cached content: TTS audio and scene images. Restores static intro music."""
    if engine.running:
        return JSONResponse({"error": "Cannot clear cache while game is running"}, status_code=409)
    deleted = 0
    for f in [f for f in CACHE_DIR.iterdir() if f.suffix in (".mp3", ".wav")]:
        f.unlink()
        deleted += 1
    for f in IMAGE_DIR.glob("*"):
        if f.is_file():
            f.unlink()
            deleted += 1
    # Restore static intro music
    for theme in ALL_THEMES.values():
        if theme.intro_music_file:
            engine.get_intro_music(theme.slug, theme.intro_music_file)
    return {"status": "cleared", "deleted": deleted}


# --- Intro Music Management ---

@app.get("/api/intro-music")
async def list_intro_music():
    """List intro music status for each theme."""
    result = []
    for slug, theme in ALL_THEMES.items():
        filename = f"intro_music_{slug}.mp3"
        filepath = CACHE_DIR / filename
        exists = filepath.exists() and filepath.stat().st_size > 0
        result.append({
            "theme": slug,
            "theme_name": theme.name,
            "filename": filename,
            "exists": exists,
            "size": filepath.stat().st_size if exists else 0,
            "static_file": theme.intro_music_file,
            "audio_url": f"/audio/{filename}?t={int(filepath.stat().st_mtime)}" if exists else None,
        })
    return {"music": result}


@app.post("/api/intro-music/{theme_slug}/generate")
async def generate_intro_music(theme_slug: str):
    """Get intro music status for a theme (static MP3 shipped with app)."""
    theme = ALL_THEMES.get(theme_slug)
    if not theme:
        return JSONResponse({"error": f"Unknown theme: {theme_slug}"}, status_code=404)

    if not theme.intro_music_file:
        return JSONResponse({"error": f"Theme {theme_slug} has no intro music"}, status_code=400)

    filename = engine.get_intro_music(theme_slug, theme.intro_music_file)
    if filename:
        return {"status": "available", "filename": filename, "audio_url": f"/audio/{filename}"}
    return JSONResponse({"error": "Intro music file not found"}, status_code=404)


# --- Theme Phrases ---

@app.get("/api/themes/phrases")
async def get_theme_phrases():
    """Return all editable phrases for all themes, with any saved overrides applied."""
    config = load_config()
    overrides = config.get("theme_phrases", {})

    result = {}
    for slug, theme in ALL_THEMES.items():
        theme_overrides = overrides.get(slug, {})
        result[slug] = {
            "name": theme.name,
            "slug": slug,
            "phrases": {
                "intro_texts": theme_overrides.get("intro_texts", theme.intro_texts),
                "outro_texts": theme_overrides.get("outro_texts", theme.outro_texts),
                "announcement_prefixes": theme_overrides.get("announcement_prefixes", theme.announcement_prefixes),
                "success_prefixes": theme_overrides.get("success_prefixes", theme.success_prefixes),
                "hint_prefixes": theme_overrides.get("hint_prefixes", theme.hint_prefixes),
                "timeout_phrases": theme_overrides.get("timeout_phrases", theme.timeout_phrases),
            },
        }
    return {"themes": result}


class PhraseUpdateRequest(BaseModel):
    theme_slug: str
    phrase_type: str  # intro_texts, outro_texts
    index: int
    text: str


@app.post("/api/themes/phrases/update")
async def update_theme_phrase(req: PhraseUpdateRequest):
    """Save a manual edit to a specific phrase."""
    theme = ALL_THEMES.get(req.theme_slug)
    if not theme:
        return JSONResponse({"error": "Unknown theme"}, status_code=404)

    VALID_PHRASE_TYPES = ("intro_texts", "outro_texts", "announcement_prefixes", "success_prefixes", "hint_prefixes", "timeout_phrases")

    if req.phrase_type not in VALID_PHRASE_TYPES:
        return JSONResponse({"error": "Invalid phrase type"}, status_code=400)

    config = load_config()
    overrides = config.setdefault("theme_phrases", {})
    theme_overrides = overrides.setdefault(req.theme_slug, {})

    # Start from existing overrides or defaults
    defaults = getattr(theme, req.phrase_type)
    phrases = list(theme_overrides.get(req.phrase_type, defaults))

    if req.index < 0 or req.index >= len(phrases):
        return JSONResponse({"error": "Index out of range"}, status_code=400)

    phrases[req.index] = req.text
    theme_overrides[req.phrase_type] = phrases
    save_config(config)

    # Apply to live theme
    _apply_phrase_overrides()

    return {"status": "updated"}


class PhraseAddRequest(BaseModel):
    theme_slug: str
    phrase_type: str
    text: str


@app.post("/api/themes/phrases/add")
async def add_theme_phrase(req: PhraseAddRequest):
    """Add a new phrase to a theme."""
    theme = ALL_THEMES.get(req.theme_slug)
    if not theme:
        return JSONResponse({"error": "Unknown theme"}, status_code=404)

    VALID_PHRASE_TYPES = ("intro_texts", "outro_texts", "announcement_prefixes", "success_prefixes", "hint_prefixes", "timeout_phrases")
    if req.phrase_type not in VALID_PHRASE_TYPES:
        return JSONResponse({"error": "Invalid phrase type"}, status_code=400)

    config = load_config()
    overrides = config.setdefault("theme_phrases", {})
    theme_overrides = overrides.setdefault(req.theme_slug, {})

    defaults = getattr(theme, req.phrase_type)
    phrases = list(theme_overrides.get(req.phrase_type, defaults))
    phrases.append(req.text)
    theme_overrides[req.phrase_type] = phrases
    save_config(config)
    _apply_phrase_overrides()

    return {"status": "added", "index": len(phrases) - 1}


class PhraseDeleteRequest(BaseModel):
    theme_slug: str
    phrase_type: str
    index: int


@app.post("/api/themes/phrases/delete")
async def delete_theme_phrase(req: PhraseDeleteRequest):
    """Delete a phrase from a theme."""
    theme = ALL_THEMES.get(req.theme_slug)
    if not theme:
        return JSONResponse({"error": "Unknown theme"}, status_code=404)

    VALID_PHRASE_TYPES = ("intro_texts", "outro_texts", "announcement_prefixes", "success_prefixes", "hint_prefixes", "timeout_phrases")
    if req.phrase_type not in VALID_PHRASE_TYPES:
        return JSONResponse({"error": "Invalid phrase type"}, status_code=400)

    config = load_config()
    overrides = config.setdefault("theme_phrases", {})
    theme_overrides = overrides.setdefault(req.theme_slug, {})

    defaults = getattr(theme, req.phrase_type)
    phrases = list(theme_overrides.get(req.phrase_type, defaults))

    if req.index < 0 or req.index >= len(phrases):
        return JSONResponse({"error": "Index out of range"}, status_code=400)
    if len(phrases) <= 1:
        return JSONResponse({"error": "Cannot delete last phrase"}, status_code=400)

    phrases.pop(req.index)
    theme_overrides[req.phrase_type] = phrases
    save_config(config)
    _apply_phrase_overrides()

    return {"status": "deleted"}


class PhraseRegenerateRequest(BaseModel):
    theme_slug: str
    phrase_type: str  # intro_texts, outro_texts
    index: int


@app.post("/api/themes/phrases/regenerate")
async def regenerate_theme_phrase(req: PhraseRegenerateRequest):
    """Regenerate a single phrase via LLM."""
    config = load_config()
    gemini_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    theme = ALL_THEMES.get(req.theme_slug)
    if not theme:
        return JSONResponse({"error": "Unknown theme"}, status_code=404)

    VALID_PHRASE_TYPES = ("intro_texts", "outro_texts", "announcement_prefixes", "success_prefixes", "hint_prefixes", "timeout_phrases")

    if req.phrase_type not in VALID_PHRASE_TYPES:
        return JSONResponse({"error": "Invalid phrase type"}, status_code=400)

    overrides = config.get("theme_phrases", {})
    theme_overrides = overrides.get(req.theme_slug, {})
    defaults = getattr(theme, req.phrase_type)
    phrases = list(theme_overrides.get(req.phrase_type, defaults))

    if req.index < 0 or req.index >= len(phrases):
        return JSONResponse({"error": "Index out of range"}, status_code=400)

    old_phrase = phrases[req.index]

    # Build LLM prompt based on phrase type
    prompt_map = {
        "intro_texts": ("an intro announcement spoken at the start of a game",
                        "It should build excitement and tell players to get ready. About 2-3 sentences."),
        "outro_texts": ("an outro/finale announcement spoken when the game ends",
                        "It should celebrate the players' achievement. Use {total_time} and {rounds} as placeholders for stats. About 2-3 sentences."),
        "announcement_prefixes": ("a short announcement prefix spoken before each mission/challenge",
                                   "Keep it to one short sentence — punchy and in character. It precedes the mission description."),
        "success_prefixes": ("a short celebration prefix spoken before the success message when a round is completed",
                             "Keep it to a few words — punchy and in character. Like 'Well done, agents.' or 'Wackadoo.'"),
        "hint_prefixes": ("a short hint prefix spoken before giving players a clue",
                          "Keep it to a few words — in character. Like 'Mission Control has a tip for you...' or 'Bingo says...'"),
        "timeout_phrases": ("a timeout/failure announcement spoken when time runs out on a mission",
                            "It should be encouraging but acknowledge the failure. Keep it to 1-2 sentences. Kid-friendly."),
    }
    purpose, note = prompt_map[req.phrase_type]

    other_phrases = [p for i, p in enumerate(phrases) if i != req.index]

    system_prompt = f"""You write character dialogue for a children's smart home challenge game.
Theme: {theme.name}
You are writing {purpose}.
{note}
Match the tone and style of these existing phrases for this theme:
{chr(10).join(f'- {p}' for p in other_phrases)}

Return ONLY the new phrase text, nothing else. No quotes, no explanation."""

    try:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        prompt = f"{system_prompt}\n\nWrite a new variation. The phrase it's replacing was: \"{old_phrase}\""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 100},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                gemini_url, json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return JSONResponse({"error": f"LLM failed: {body[:200]}"}, status_code=500)
                data = await resp.json()

        new_text = data["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"')

        # Save the override
        overrides = config.setdefault("theme_phrases", {})
        theme_ov = overrides.setdefault(req.theme_slug, {})
        phrases[req.index] = new_text
        theme_ov[req.phrase_type] = phrases
        save_config(config)
        _apply_phrase_overrides()

        return {"status": "regenerated", "text": new_text}

    except Exception as e:
        logger.error(f"Phrase regeneration failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/themes/phrases/reset")
async def reset_theme_phrases(theme_slug: str = "", phrase_type: str = ""):
    """Reset phrases for a theme back to defaults."""
    if theme_slug and theme_slug not in ALL_THEMES:
        return JSONResponse({"error": "Unknown theme"}, status_code=404)

    config = load_config()
    overrides = config.get("theme_phrases", {})

    if theme_slug and phrase_type:
        if theme_slug in overrides and phrase_type in overrides[theme_slug]:
            del overrides[theme_slug][phrase_type]
    elif theme_slug:
        overrides.pop(theme_slug, None)
    else:
        config["theme_phrases"] = {}

    save_config(config)
    _apply_phrase_overrides()
    return {"status": "reset"}


def _apply_phrase_overrides():
    """Apply saved phrase overrides to the live theme objects, restoring defaults first."""
    config = load_config()
    overrides = config.get("theme_phrases", {})
    for slug, theme in ALL_THEMES.items():
        defaults = _THEME_DEFAULTS[slug]
        theme_ov = overrides.get(slug, {})
        for field in defaults:
            if field in theme_ov:
                setattr(theme, field, copy.deepcopy(theme_ov[field]))
            else:
                setattr(theme, field, copy.deepcopy(defaults[field]))


# --- Scene Image Management ---

def _get_image_gen() -> ImageGenerator | None:
    """Get an ImageGenerator using the configured Gemini key."""
    config = load_config()
    api_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    return ImageGenerator(api_key, str(CACHE_DIR))


def _get_all_image_prompts() -> list[dict]:
    """Build list of all scene image prompts across themes."""
    prompts = []
    for slug, theme in ALL_THEMES.items():
        for prompt_type, label, prompt in [
            ("intro", "Intro Scene", theme.intro_scene_prompt),
            ("outro", "Outro Scene", theme.outro_scene_prompt),
            ("transition", "Transition", theme.transition_prompt),
        ]:
            if prompt:
                prompts.append({
                    "theme": slug,
                    "theme_name": theme.name,
                    "type": prompt_type,
                    "label": label,
                    "prompt": prompt,
                })
    return prompts


@app.get("/api/scene-images")
async def list_scene_images():
    """List scene image status for each theme prompt."""
    gen = _get_image_gen()
    result = []
    for info in _get_all_image_prompts():
        prompt = info["prompt"]
        cached = gen.is_cached(prompt) if gen else False
        filename = gen.cached_filename(prompt) if gen and cached else None
        size = gen.cached_size(prompt) if gen and cached else 0
        result.append({
            **info,
            "exists": cached,
            "filename": filename,
            "size": size,
            "image_url": f"/images/{filename}" if filename else None,
        })
    return {"images": result}


@app.post("/api/scene-images/generate")
async def generate_scene_image(theme_slug: str = "", image_type: str = ""):
    """Generate (or regenerate) a single scene image."""
    if engine.running:
        return JSONResponse({"error": "Cannot generate while game is running"}, status_code=409)

    gen = _get_image_gen()
    if not gen:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    # Find the matching prompt
    for info in _get_all_image_prompts():
        if info["theme"] == theme_slug and info["type"] == image_type:
            # Delete existing so it regenerates
            gen.delete_cached(info["prompt"])
            filename = await gen.generate(info["prompt"])
            if filename:
                return {"status": "generated", "filename": filename, "image_url": f"/images/{filename}"}
            return JSONResponse({"error": "Generation failed"}, status_code=500)

    return JSONResponse({"error": "Prompt not found"}, status_code=404)


@app.post("/api/scene-images/generate-all")
async def generate_all_scene_images():
    """Generate all missing scene images for all themes."""
    if engine.running:
        return JSONResponse({"error": "Cannot generate while game is running"}, status_code=409)

    gen = _get_image_gen()
    if not gen:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    generated = 0
    cached = 0
    failed = 0
    for info in _get_all_image_prompts():
        if gen.is_cached(info["prompt"]):
            cached += 1
            continue
        filename = await gen.generate(info["prompt"])
        if filename:
            generated += 1
        else:
            failed += 1

    return {"status": "done", "generated": generated, "cached": cached, "failed": failed}


@app.delete("/api/scene-images")
async def delete_scene_image(theme_slug: str = "", image_type: str = ""):
    """Delete a cached scene image."""
    gen = _get_image_gen()
    if not gen:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    for info in _get_all_image_prompts():
        if info["theme"] == theme_slug and info["type"] == image_type:
            deleted = gen.delete_cached(info["prompt"])
            return {"status": "deleted" if deleted else "not_found"}

    return JSONResponse({"error": "Prompt not found"}, status_code=404)


@app.delete("/api/scene-images/all")
async def delete_all_scene_images():
    """Delete all cached scene images."""
    gen = _get_image_gen()
    if not gen:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    deleted = 0
    for info in _get_all_image_prompts():
        if gen.delete_cached(info["prompt"]):
            deleted += 1
    return {"status": "deleted", "count": deleted}


class PreviewRequest(BaseModel):
    rounds: int = 5
    difficulty: str = "mixed"
    floors: list[str] | None = None


@app.post("/api/challenges/preview")
async def preview_challenges(req: PreviewRequest):
    """Return the challenge set that would be used for a game, without starting."""
    challenges = engine.select_challenges(req.difficulty, req.rounds, floors=req.floors)
    result = []
    for c in challenges:
        result.append({
            "id": None,  # we'll look up by name below
            "name": c.name,
            "room": c.room,
            "difficulty": c.difficulty.value,
            "floor": c.floor,
            "success_speaker": c.success_speaker,
            "targets": [{"entity_id": t.entity_id, "target_state": t.target_state} for t in c.targets],
            "multi_target": c.multi_target,
        })
    # Look up IDs from the database
    all_db = challenge_db.load()
    name_to_id = {c["name"]: c["id"] for c in all_db}
    for r in result:
        r["id"] = name_to_id.get(r["name"], "")
    return {"challenges": result}


class ShuffleRequest(BaseModel):
    exclude_ids: list[str]
    difficulty: str = "mixed"
    floors: list[str] | None = None


@app.post("/api/challenges/shuffle-one")
async def shuffle_one_challenge(req: ShuffleRequest):
    """Return one random challenge not in exclude_ids."""
    all_challenges = engine.select_challenges(req.difficulty, 999, floors=req.floors)
    exclude = set(req.exclude_ids)
    # Look up IDs
    all_db = challenge_db.load()
    name_to_id = {c["name"]: c["id"] for c in all_db}
    candidates = [c for c in all_challenges if name_to_id.get(c.name, "") not in exclude]
    if not candidates:
        return JSONResponse({"error": "No more challenges available"}, status_code=404)
    pick = random.choice(candidates)
    return {
        "challenge": {
            "id": name_to_id.get(pick.name, ""),
            "name": pick.name,
            "room": pick.room,
            "difficulty": pick.difficulty.value,
            "floor": pick.floor,
            "success_speaker": pick.success_speaker,
            "targets": [{"entity_id": t.entity_id, "target_state": t.target_state} for t in pick.targets],
            "multi_target": pick.multi_target,
        }
    }


@app.post("/api/start")
async def start_game(req: StartRequest):
    if engine.running:
        return JSONResponse({"error": "Game already running"}, status_code=409)

    if not engine.gemini_api_key:
        return JSONResponse({"error": "Gemini API key not configured."}, status_code=400)

    # Clamp rounds to valid range (up to 50 for dynamic challenges)
    rounds = max(1, min(req.rounds, 50))

    # Allow runtime overrides
    if req.ha_url:
        engine.update_ha_url(req.ha_url)

    if req.hub_speaker:
        engine.hub_speaker = req.hub_speaker

    engine.appletv_mode = req.appletv_mode
    engine.local_mode = req.local_mode

    asyncio.create_task(engine.run_game(req.theme, rounds, req.difficulty, floors=req.floors, challenge_ids=req.challenge_ids))
    return {"status": "starting"}


@app.post("/api/skip")
async def skip_round():
    if not engine.running:
        return JSONResponse({"error": "No game running"}, status_code=409)
    engine.request_skip()
    return {"status": "skipping"}


@app.post("/api/stop")
async def stop_game():
    if not engine.running:
        return JSONResponse({"error": "No game running"}, status_code=409)
    engine.request_stop()
    return {"status": "stopping"}


@app.post("/api/advance")
async def advance_mission():
    """Advance to the next round in Apple TV mode."""
    if not engine.running:
        return JSONResponse({"error": "No game running"}, status_code=409)
    engine.request_advance()
    return {"status": "advancing"}


# --- Challenge Generation Endpoints ---

ACTIONABLE_DOMAINS = {"light", "switch", "fan", "cover", "binary_sensor", "sensor", "lock", "climate"}
EXCLUDE_PATTERNS = {"_battery", "_signal", "_update", "_firmware", "_linkquality", "_rssi"}

# Domains worth sending to the LLM for challenge generation (subset of ACTIONABLE_DOMAINS)
LLM_DOMAINS = {"light", "switch", "fan", "cover", "binary_sensor", "lock"}

# Additional exclude patterns for LLM — infrastructure entities kids can't interact with
LLM_EXCLUDE_PATTERNS = {
    "adaptive_lighting", "child_lock", "do_not_disturb", "night_mode",
    "disable_led", "slzb", "roborock", "rusty_dusty", "gerald", "geoffrey",
    "remote_ui", "mop_", "water_box", "water_shortage", "dock_",
    "_charging", "_cleaning", "flume_", "backup_", "sun_next_",
    "average_ping", "chores_", "pixel_tablet", "_drying",
    # Camera switches (detections, overlays, status lights, system sounds, privacy)
    "detections_", "overlay_show_", "status_light_on", "system_sounds",
    "privacy_mode", "nvr_", "studio_mode", "energy_saving",
    # mmWave/radar sensor config switches
    "mmwave", "ld2410", "ld2450", "radar_engineering", "multi_target_tracking",
    "bed_presence", "startup_light_blink", "reduce_db_reporting",
    # Garage door controller internals
    "ratgdo_", "learn",
    # Appliance internals
    "express_mode", "smart_away", "dehumidifier",
    # Sonos audio config switches
    "crossfade", "loudness", "surround_music", "night_sound",
    "speech_enhancement", "subwoofer_enabled", "surround_enabled",
    # Appliance/network/sprinkler internals
    "dishwasher_", "rachio_", "hmr_", "enable_camera",
    # Other integration switches
    "schedule_", "auto_off", "led_indicator", "power_outage",
    "button_delay", "smart_bulb_mode",
}

# Only these binary_sensor patterns are useful for challenges
BINARY_SENSOR_KEEP_PATTERNS = {"_door", "_window", "_contact", "_motion", "_occupancy", "_lock"}

HA_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def _fetch_ha_registries(ha_url: str, ha_token: str):
    """Fetch area, device, and entity registries from HA via WebSocket.

    Returns (areas_map, device_areas, entity_area_map, entity_device_map).
    """
    areas_map = {}
    device_areas = {}
    entity_area_map = {}
    entity_device_map = {}

    ws_url = ha_url.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, timeout=15) as ws:
                # Authenticate
                await ws.receive_json()  # auth_required
                await ws.send_json({"type": "auth", "access_token": ha_token})
                auth_result = await ws.receive_json()
                if auth_result.get("type") != "auth_ok":
                    logger.warning("HA WebSocket auth failed")
                    return areas_map, device_areas, entity_area_map, entity_device_map

                # Fetch area registry
                await ws.send_json({"id": 1, "type": "config/area_registry/list"})
                result = await ws.receive_json()
                if result.get("success"):
                    for a in result.get("result", []):
                        aid = a.get("area_id") or a.get("id")
                        if aid:
                            areas_map[aid] = a["name"]

                # Fetch device registry
                await ws.send_json({"id": 2, "type": "config/device_registry/list"})
                result = await ws.receive_json()
                if result.get("success"):
                    for d in result.get("result", []):
                        if d.get("area_id"):
                            device_areas[d["id"]] = areas_map.get(d["area_id"], "")

                # Fetch entity registry
                await ws.send_json({"id": 3, "type": "config/entity_registry/list"})
                result = await ws.receive_json()
                if result.get("success"):
                    for e in result.get("result", []):
                        eid = e.get("entity_id", "")
                        if e.get("area_id"):
                            entity_area_map[eid] = areas_map.get(e["area_id"], "")
                        if e.get("device_id"):
                            entity_device_map[eid] = e["device_id"]
    except Exception as e:
        logger.warning(f"Could not fetch HA registries via WebSocket: {e}")

    return areas_map, device_areas, entity_area_map, entity_device_map


def _resolve_area(eid: str, entity_area_map: dict, entity_device_map: dict, device_areas: dict) -> str:
    """Resolve area for an entity: entity area > device area > Unknown."""
    area = entity_area_map.get(eid, "")
    if not area:
        device_id = entity_device_map.get(eid, "")
        if device_id:
            area = device_areas.get(device_id, "")
    return area or "Unknown"


@app.get("/api/ha/entities")
async def get_ha_entities():
    """Fetch and filter actionable HA entities with area info."""
    config = load_config()
    ha_url = (config.get("ha_url") or os.environ.get("HA_URL", "")).rstrip("/")
    ha_token = config.get("ha_token") or os.environ.get("HA_TOKEN", "")

    if not ha_url or not ha_token:
        return JSONResponse({"error": "HA URL and token must be configured"}, status_code=400)

    headers = {"Authorization": f"Bearer {ha_token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{ha_url}/api/states", headers=headers,
                               timeout=HA_REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return JSONResponse({"error": f"HA states API returned {resp.status}"}, status_code=502)
            states = await resp.json()

    _, device_areas, entity_area_map, entity_device_map = await _fetch_ha_registries(ha_url, ha_token)

    entities = []
    for s in states:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        state = s["state"]

        if domain not in ACTIONABLE_DOMAINS:
            continue
        if state == "unavailable":
            continue
        if any(pat in eid for pat in EXCLUDE_PATTERNS):
            continue

        entities.append({
            "entity_id": eid,
            "state": state,
            "friendly_name": s.get("attributes", {}).get("friendly_name", eid),
            "domain": domain,
            "area": _resolve_area(eid, entity_area_map, entity_device_map, device_areas),
        })

    return entities


@app.get("/api/ha/speakers")
async def get_ha_speakers():
    """Fetch media_player entities for speaker assignment."""
    config = load_config()
    ha_url = (config.get("ha_url") or os.environ.get("HA_URL", "")).rstrip("/")
    ha_token = config.get("ha_token") or os.environ.get("HA_TOKEN", "")

    if not ha_url or not ha_token:
        return JSONResponse({"error": "HA URL and token must be configured"}, status_code=400)

    headers = {"Authorization": f"Bearer {ha_token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(f"{ha_url}/api/states", headers=headers,
                               timeout=HA_REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return JSONResponse({"error": f"HA states API returned {resp.status}"}, status_code=502)
            states = await resp.json()

    _, device_areas, entity_area_map, entity_device_map = await _fetch_ha_registries(ha_url, ha_token)

    speakers = []
    for s in states:
        eid = s["entity_id"]
        if not eid.startswith("media_player."):
            continue
        if s["state"] == "unavailable":
            continue

        speakers.append({
            "entity_id": eid,
            "friendly_name": s.get("attributes", {}).get("friendly_name", eid),
            "area": _resolve_area(eid, entity_area_map, entity_device_map, device_areas),
        })

    return speakers


class SuggestRequest(BaseModel):
    entities: list[dict] | None = None
    speakers: list[dict] | None = None
    hub_speaker: str | None = None
    user_prompt: str | None = None


@app.post("/api/challenges/suggest")
async def suggest_challenges(req: SuggestRequest):
    """Send entities to LLM via Gemini for challenge suggestions."""
    global pending_suggestions

    config = load_config()
    gemini_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    # If entities/speakers not provided, fetch them
    entities = req.entities
    speakers = req.speakers
    hub_speaker = req.hub_speaker or config.get("hub_speaker", "media_player.hub_speaker")

    if not entities:
        # Fetch from HA
        entities_resp = await get_ha_entities()
        if isinstance(entities_resp, JSONResponse):
            return entities_resp
        entities = entities_resp

    if not speakers:
        # Use allowed speakers from config, fall back to all HA speakers
        allowed_speakers = config.get("allowed_speakers", [])
        if allowed_speakers:
            speakers = allowed_speakers
        else:
            speakers_resp = await get_ha_speakers()
            if isinstance(speakers_resp, JSONResponse):
                return speakers_resp
            speakers = speakers_resp

    if not entities:
        return JSONResponse({"error": "No actionable entities found in Home Assistant"}, status_code=400)

    # Aggressively filter for LLM — remove non-interactive entities to reduce tokens
    before_llm = len(entities)
    llm_entities = []
    for e in entities:
        eid = e["entity_id"]
        domain = e["domain"]

        # Only send challenge-worthy domains
        if domain not in LLM_DOMAINS:
            continue

        # Filter out infrastructure entities
        if any(pat in eid for pat in LLM_EXCLUDE_PATTERNS):
            continue

        # Binary sensors: only keep doors, windows, motion, occupancy
        if domain == "binary_sensor":
            if not any(pat in eid for pat in BINARY_SENSOR_KEEP_PATTERNS):
                continue

        # Skip switches that look like automations/integrations (heuristic: no area assigned)
        if domain == "switch" and e.get("area") == "Unknown":
            continue

        llm_entities.append(e)

    entities = llm_entities
    logger.info(f"LLM filter: {before_llm} → {len(entities)} entities")

    # Filter out blacklisted entities
    blacklist = set(challenge_db.load_blacklist())
    if blacklist:
        before = len(entities)
        entities = [e for e in entities if e["entity_id"] not in blacklist]
        logger.info(f"Filtered {before - len(entities)} blacklisted entities, {len(entities)} remaining")

    if not entities:
        return JSONResponse({"error": "No available entities. All are blacklisted."}, status_code=400)

    # Summarize existing challenges so the LLM avoids duplicates
    approved = challenge_db.load()
    existing_summary = []
    for c in approved:
        target_ids = [t.get("entity_id", "") for t in c.get("targets", [])]
        target_states = [t.get("target_state", "") for t in c.get("targets", [])]
        existing_summary.append({
            "name": c.get("name", ""),
            "targets": [f"{eid} → {state}" for eid, state in zip(target_ids, target_states)],
            "difficulty": c.get("difficulty", ""),
        })

    try:
        generator = ChallengeGenerator(gemini_key)
        suggestions = await generator.suggest(
            entities, speakers, hub_speaker,
            user_prompt=req.user_prompt or "",
            floors=config.get("floors", []) or None,
            existing_challenges=existing_summary if existing_summary else None,
        )
    except Exception as e:
        logger.error(f"Challenge generation failed: {e}")
        return JSONResponse({"error": f"Challenge generation failed: {str(e)}"}, status_code=500)

    # Store suggestions with temporary IDs
    pending_suggestions = {}
    for s in suggestions:
        temp_id = str(uuid.uuid4())
        s["id"] = temp_id
        pending_suggestions[temp_id] = s

    return {"suggestions": suggestions}


class ApproveRequest(BaseModel):
    challenge_id: str
    approved: bool
    overrides: dict | None = None


@app.post("/api/challenges/approve")
async def approve_challenge(req: ApproveRequest):
    """Approve or deny a suggested challenge. Deny blacklists the entities."""
    if req.challenge_id not in pending_suggestions:
        return JSONResponse({"error": "Challenge not found in pending suggestions"}, status_code=404)

    challenge = pending_suggestions.pop(req.challenge_id)
    if req.approved:
        # Apply any field overrides from the UI before saving
        if req.overrides:
            for key in ("difficulty", "floor", "success_speaker"):
                if key in req.overrides:
                    challenge[key] = req.overrides[key]
        challenge_db.add(challenge)
        return {"status": "approved", "id": challenge["id"]}
    else:
        # Blacklist entities from denied challenges
        entity_ids = [t["entity_id"] for t in challenge.get("targets", [])]
        if entity_ids:
            challenge_db.add_to_blacklist(entity_ids)
        return {"status": "denied", "blacklisted": entity_ids}


@app.post("/api/challenges/approve-all")
async def approve_all_challenges():
    """Bulk approve all remaining pending suggestions."""
    global pending_suggestions
    count = 0
    for challenge in pending_suggestions.values():
        challenge_db.add(challenge)
        count += 1
    pending_suggestions = {}
    return {"status": "approved", "count": count}


class RethinkRequest(BaseModel):
    challenge_id: str
    feedback: str


@app.post("/api/challenges/rethink")
async def rethink_challenge(req: RethinkRequest):
    """Re-think a single challenge with user feedback via Gemini."""
    if req.challenge_id not in pending_suggestions:
        return JSONResponse({"error": "Challenge not found in pending suggestions"}, status_code=404)

    config = load_config()
    gemini_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    challenge = pending_suggestions[req.challenge_id]
    hub_speaker = config.get("hub_speaker", "media_player.hub_speaker")

    # Use cached entities if available, otherwise fetch from HA
    entities = getattr(rethink_challenge, '_cached_entities', None)
    if not entities:
        entities_resp = await get_ha_entities()
        if isinstance(entities_resp, JSONResponse):
            entities = []
        else:
            entities = entities_resp

    # Use allowed speakers from config
    speakers = config.get("allowed_speakers", [])
    if not speakers:
        speakers_resp = await get_ha_speakers()
        if isinstance(speakers_resp, JSONResponse):
            speakers = []
        else:
            speakers = speakers_resp

    try:
        generator = ChallengeGenerator(gemini_key)
        revised = await generator.rethink(challenge, req.feedback, entities, speakers, hub_speaker)
    except Exception as e:
        logger.error(f"Rethink failed: {e}")
        return JSONResponse({"error": f"Rethink failed: {str(e)}"}, status_code=500)

    # Replace the pending suggestion with the revised version
    revised["id"] = req.challenge_id
    pending_suggestions[req.challenge_id] = revised

    return {"challenge": revised}


class RegenerateFieldRequest(BaseModel):
    challenge_id: str
    field: str  # announcement, hint, success_message, funny_announcements
    source: str = "approved"  # "approved" or "pending"


@app.post("/api/challenges/regenerate-field")
async def regenerate_field(req: RegenerateFieldRequest):
    """Regenerate a single text field of a challenge via LLM."""
    config = load_config()
    gemini_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return JSONResponse({"error": "Gemini API key not configured"}, status_code=400)

    # Find the challenge
    if req.source == "pending" and req.challenge_id in pending_suggestions:
        challenge = pending_suggestions[req.challenge_id]
    elif req.source == "approved":
        all_challenges = challenge_db.load()
        challenge = next((c for c in all_challenges if c["id"] == req.challenge_id), None)
        if not challenge:
            return JSONResponse({"error": "Challenge not found"}, status_code=404)
    else:
        return JSONResponse({"error": "Challenge not found"}, status_code=404)

    try:
        generator = ChallengeGenerator(gemini_key)
        new_value = await generator.regenerate_field(challenge, req.field)
    except Exception as e:
        logger.error(f"Regenerate field failed: {e}")
        return JSONResponse({"error": f"Regeneration failed: {str(e)}"}, status_code=500)

    # Update the challenge
    if req.source == "pending":
        pending_suggestions[req.challenge_id][req.field] = new_value
    else:
        challenge_db.update(req.challenge_id, {req.field: new_value})

    return {"field": req.field, "value": new_value}


@app.get("/api/challenges")
async def list_challenges():
    """List all approved challenges from the database."""
    challenges = challenge_db.load()
    return {"challenges": challenges, "count": len(challenges)}


@app.delete("/api/challenges/{challenge_id}")
async def delete_challenge(challenge_id: str):
    """Remove a challenge from the database."""
    challenge_db.remove(challenge_id)
    return {"status": "deleted"}


@app.put("/api/challenges/{challenge_id}")
async def update_challenge(challenge_id: str, req: dict):
    """Update fields of a challenge."""
    challenge_db.update(challenge_id, req)
    return {"status": "updated"}




# --- Entity Blacklist Endpoints ---

@app.get("/api/blacklist")
async def get_blacklist():
    """List blacklisted entity IDs."""
    bl = challenge_db.load_blacklist()
    return {"blacklist": bl, "count": len(bl)}


class BlacklistRemoveRequest(BaseModel):
    entity_ids: list[str]


@app.post("/api/blacklist/remove")
async def remove_from_blacklist(req: BlacklistRemoveRequest):
    """Remove entities from the blacklist."""
    challenge_db.remove_from_blacklist(req.entity_ids)
    return {"status": "removed", "removed": req.entity_ids}


@app.post("/api/blacklist/clear")
async def clear_blacklist():
    """Clear the entire blacklist."""
    challenge_db.clear_blacklist()
    return {"status": "cleared"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "state_sync", **engine.get_state()}))
        while True:
            data = await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
