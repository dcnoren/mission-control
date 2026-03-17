"""AI image generation via OpenRouter (Nano Banana Pro)."""
import base64
import hashlib
import logging
import re
from pathlib import Path

import aiohttp

logger = logging.getLogger("mission_control.image_gen")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-3-pro-image-preview"
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
            logger.warning("No OpenRouter API key — skipping image generation")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": MODEL,
                "modalities": ["image", "text"],
                "messages": [
                    {"role": "user", "content": f"Generate this image: {prompt}"}
                ],
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    OPENROUTER_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"OpenRouter image gen failed ({resp.status}): {body[:200]}")
                        return None

                    data = await resp.json()

            # Extract base64 image from response
            choices = data.get("choices", [])
            if not choices:
                logger.error("No choices in OpenRouter response")
                return None

            message = choices[0].get("message", {})

            # OpenRouter returns images in message.images[] as data URIs
            image_data = None
            images = message.get("images", [])
            if images:
                for img in images:
                    if isinstance(img, dict) and img.get("type") == "image_url":
                        url = img.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            image_data = url.split(",", 1)[-1]
                            break

            # Fallback: check content field (list of parts or string)
            if not image_data:
                content = message.get("content", "")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            if "inline_data" in part:
                                image_data = part["inline_data"].get("data")
                                break
                            if part.get("type") == "image_url":
                                url = part.get("image_url", {}).get("url", "")
                                if url.startswith("data:"):
                                    image_data = url.split(",", 1)[-1]
                                    break
                elif isinstance(content, str) and content:
                    match = re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)', content)
                    if match:
                        image_data = match.group(1)

            if not image_data:
                logger.error("No image data found in OpenRouter response")
                logger.debug(f"Message keys: {list(message.keys())}")
                return None

            # Decode and save
            img_bytes = base64.b64decode(image_data)
            cached.write_bytes(img_bytes)
            logger.info(f"Generated image: {cached.name} ({len(img_bytes)} bytes)")
            return cached.name

        except Exception as e:
            logger.error(f"Image generation error: {e}")
            return None
