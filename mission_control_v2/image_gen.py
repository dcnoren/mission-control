"""AI image generation via Gemini API."""
import base64
import hashlib
import logging
from pathlib import Path

import aiohttp

logger = logging.getLogger("mission_control.image_gen")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=120)


class ImageGenerator:
    def __init__(self, api_key: str, cache_dir: str):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir) / "images"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, prompt: str) -> Path:
        h = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return self.cache_dir / f"{h}.png"

    def is_cached(self, prompt: str) -> bool:
        """Check if an image for this prompt is already cached."""
        cached = self._cache_path(prompt)
        return cached.exists() and cached.stat().st_size > 0

    def cached_filename(self, prompt: str) -> str | None:
        """Return cached filename if exists, else None."""
        cached = self._cache_path(prompt)
        if cached.exists() and cached.stat().st_size > 0:
            return cached.name
        return None

    def cached_size(self, prompt: str) -> int:
        """Return cached file size in bytes, or 0."""
        cached = self._cache_path(prompt)
        if cached.exists():
            return cached.stat().st_size
        return 0

    def delete_cached(self, prompt: str) -> bool:
        """Delete cached image for a prompt. Returns True if file existed."""
        cached = self._cache_path(prompt)
        if cached.exists():
            cached.unlink()
            return True
        return False

    async def generate(self, prompt: str) -> str | None:
        """Generate image from prompt. Returns filename (relative to images dir) or None."""
        cached = self._cache_path(prompt)
        if cached.exists() and cached.stat().st_size > 0:
            logger.info(f"Image cache hit: {cached.name}")
            return cached.name

        if not self.api_key:
            logger.warning("No Gemini API key — skipping image generation")
            return None

        try:
            url = f"{GEMINI_URL}?key={self.api_key}"
            payload = {
                "contents": [
                    {"parts": [{"text": f"Generate this image: {prompt}"}]}
                ],
                "generationConfig": {
                    "responseModalities": ["IMAGE", "TEXT"],
                },
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Gemini image gen failed ({resp.status}): {body[:200]}")
                        return None

                    data = await resp.json()

            # Extract base64 image from Gemini response
            candidates = data.get("candidates", [])
            if not candidates:
                logger.error("No candidates in Gemini response")
                return None

            parts = candidates[0].get("content", {}).get("parts", [])
            image_data = None
            for part in parts:
                if "inlineData" in part:
                    mime = part["inlineData"].get("mimeType", "")
                    if mime.startswith("image/"):
                        image_data = part["inlineData"]["data"]
                        break

            if not image_data:
                logger.error("No image data found in Gemini response")
                logger.debug(f"Response parts: {[list(p.keys()) for p in parts]}")
                return None

            # Decode and save
            img_bytes = base64.b64decode(image_data)
            cached.write_bytes(img_bytes)
            logger.info(f"Generated image: {cached.name} ({len(img_bytes)} bytes)")
            return cached.name

        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return None
