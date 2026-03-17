"""One-off script: send sample audio clips to GPT-4o via OpenRouter for analysis."""
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, "/app")

from challenges import ALL_CHALLENGES
from themes import ALL_THEMES

CACHE_DIR = Path("/app/data/cache")
CONFIG_FILE = Path("/app/data/config.json")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def cache_key(text: str, voice_id: str) -> str:
    h = hashlib.sha256(f"{voice_id}:{text}".encode()).hexdigest()[:16]
    return f"{h}.mp3"


def get_samples():
    """Pick a representative set of clips to analyze."""
    theme = ALL_THEMES["mission_control"]
    bluey = ALL_THEMES["bluey"]
    snoop = ALL_THEMES["snoop_and_sniffy"]
    c = ALL_CHALLENGES[0]

    candidates = [
        ("INTRO (Mission Control)", theme.intro_texts[0], theme.announcer_voice, "Daniel"),
        ("STANDARD ANNOUNCEMENT", theme.wrap_announcement(c.announcement), theme.announcer_voice, "Daniel"),
        ("FUNNY ANNOUNCEMENT", theme.wrap_announcement(c.funny_announcements[0]), theme.announcer_voice, "Daniel"),
        ("SUCCESS MESSAGE", theme.wrap_success(c.success_message.format(time="5.0")), theme.celebration_voice, "Daniel"),
        ("HINT", theme.wrap_hint(c.hint), theme.announcer_voice, "Daniel"),
        ("OUTRO (Mission Control)", theme.outro_texts[0].format(total_time="45.0", rounds=5), theme.celebration_voice, "Daniel"),
        ("INTRO (Bluey)", bluey.intro_texts[0], bluey.announcer_voice, "Charlie"),
        ("INTRO (Snoop & Sniffy)", snoop.intro_texts[0], snoop.announcer_voice, "George"),
    ]

    samples = []
    for label, text, voice_id, voice_name in candidates:
        f = CACHE_DIR / cache_key(text, voice_id)
        if f.exists():
            samples.append({"label": label, "text": text, "voice": voice_name, "file": f})
    return samples


SYSTEM_PROMPT = """You are an audio quality analyst for a kids' smart home challenge game called "Mission Control".
The game uses ElevenLabs TTS to generate voice announcements played on Sonos speakers in a house.
Kids aged 4-8 run around the house completing challenges (turning on lights, opening doors, triggering cameras).

Current ElevenLabs settings:
- Model: eleven_multilingual_v2
- stability: 0.6
- similarity_boost: 0.8
- style: 0.4
- speed: 0.85

Voices used:
- Daniel (onwK4e9ZLuTAKqWW03F9) - British news presenter, used for Mission Control theme
- Charlie (IKne3meq5aSn9XLyUdCD) - Casual Australian, used for Bluey theme
- George (JBFqnCBsd6RMkjVDRZzb) - Warm British, used for Snoop and Sniffy theme
- Lily (pFZP5JQG7iQjIQuC4Bku) - British childlike narrator, used for Bluey celebration
- Dorothy (ThT5KcBeYPX3keUQqHPh) - British children's storyteller, used for Snoop celebration

Important constraints:
- Text uses periods NOT exclamation marks (exclamation marks cause stilted ElevenLabs audio)
- Ellipses (...) are used to create pauses in the speech
- Audio plays on Sonos speakers in rooms of a house
- Target audience is kids 4-8 years old playing a cooperative running-around-the-house game"""


async def analyze():
    config = json.loads(CONFIG_FILE.read_text())
    openrouter_key = config.get("openrouter_api_key", "")
    if not openrouter_key:
        print("ERROR: No OpenRouter API key configured.")
        print("Add it via the web UI settings or manually:")
        print('  Add "openrouter_api_key": "sk-or-..." to /app/data/config.json')
        return

    samples = get_samples()
    print(f"Found {len(samples)} sample clips to analyze\n")

    if not samples:
        print("ERROR: No cached audio files found. Run a game first to generate audio.")
        return

    # Build messages with audio for GPT-4o
    user_content = []
    user_content.append({
        "type": "text",
        "text": "I'm sending you audio samples from our game. For each one I'll provide the label, voice name, and the text that was sent to ElevenLabs, followed by the actual audio output.\n\nPlease analyze each clip for:\n1. **Pacing** - Too fast, too slow, or just right? Are pauses respected?\n2. **Tone** - Does it match the intended character?\n3. **Naturalness** - Real person feel or robotic? Any artifacts, clicks, or weird sounds?\n4. **Kid-friendliness** - Would kids 4-8 enjoy this? Is it engaging and clear?\n5. **Clarity** - Every word understandable on a speaker?\n\nAfter all clips, provide:\n- **Overall Assessment**\n- **Specific voice_settings changes** (exact numbers for stability, similarity_boost, style, speed)\n- **Text rewrites** for any clips that would sound better with different wording\n- **Per-voice recommendations** if different voices need different settings\n\nBe specific and actionable. Give me code-ready values I can plug in.",
    })

    for sample in samples:
        user_content.append({
            "type": "text",
            "text": f"\n--- {sample['label']} ---\nVoice: {sample['voice']}\nText: \"{sample['text']}\"",
        })

        audio_b64 = base64.standard_b64encode(sample["file"].read_bytes()).decode()
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:audio/mp3;base64,{audio_b64}",
            },
        })

    print("Sending to GPT-4o via OpenRouter...\n")

    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "google/gemini-2.5-pro-preview",
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=180),
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                text = result["choices"][0]["message"]["content"]
                print("=" * 60)
                print("GEMINI 2.5 PRO AUDIO ANALYSIS")
                print("=" * 60)
                print(text)
                print("=" * 60)

                analysis_file = Path("/app/data/audio_analysis.txt")
                analysis_file.write_text(text)
                print(f"\nAnalysis saved to {analysis_file}")
            else:
                body = await resp.text()
                print(f"ERROR: OpenRouter returned {resp.status}: {body[:500]}")


if __name__ == "__main__":
    asyncio.run(analyze())
