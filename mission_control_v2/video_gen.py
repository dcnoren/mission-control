"""Video card generator for Apple TV display — Pillow + ffmpeg."""
import hashlib
import logging
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("mission_control.video_gen")

CARD_WIDTH = 1920
CARD_HEIGHT = 1080
BG_COLOR = (15, 23, 41)  # #0f1729
ACCENT_COLOR = (79, 195, 247)  # #4fc3f7
TEXT_COLOR = (232, 234, 240)  # #e8eaf0
SECONDARY_COLOR = (136, 153, 170)  # #8899aa

# Difficulty badge colors
DIFFICULTY_COLORS = {
    "easy": (102, 187, 106),
    "medium": (255, 167, 38),
    "hard": (239, 83, 80),
}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font, falling back to default if system fonts unavailable."""
    # Try common system paths
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


class VideoCardGenerator:
    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.video_dir = self.cache_dir / "video"
        self.video_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, *parts: str) -> str:
        h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
        return h

    def _draw_rounded_rect(self, draw: ImageDraw.Draw, xy, radius, fill):
        x0, y0, x1, y1 = xy
        draw.rounded_rectangle(xy, radius=radius, fill=fill)

    def _render_card_image(
        self,
        lines: list[tuple[str, tuple, int, bool]],
        theme_color: tuple = ACCENT_COLOR,
    ) -> Image.Image:
        """Render a card image with centered text lines.
        Each line is (text, color, font_size, bold)."""
        img = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)

        # Subtle border
        draw.rectangle(
            [20, 20, CARD_WIDTH - 20, CARD_HEIGHT - 20],
            outline=(*theme_color, 80) if len(theme_color) == 3 else theme_color,
            width=2,
        )

        # Calculate total height for vertical centering
        rendered = []
        total_h = 0
        for text, color, size, bold in lines:
            font = _get_font(size, bold)
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            rendered.append((text, color, font, w, h))
            total_h += h + 20  # 20px line gap

        y = (CARD_HEIGHT - total_h) // 2
        for text, color, font, w, h in rendered:
            x = (CARD_WIDTH - w) // 2
            draw.text((x, y), text, fill=color, font=font)
            y += h + 20

        return img

    def generate_mission_card(
        self,
        round_num: int,
        total: int,
        name: str,
        room: str,
        difficulty: str,
        theme_color: tuple = ACCENT_COLOR,
        audio_path: str | None = None,
    ) -> str:
        """Generate a mission card MP4. Returns path to the video file."""
        key = self._cache_key(
            "mission", str(round_num), str(total), name, room, difficulty,
            str(audio_path or ""),
        )
        mp4_path = self.video_dir / f"mission_{key}.mp4"
        if mp4_path.exists():
            return str(mp4_path)

        diff_color = DIFFICULTY_COLORS.get(difficulty, ACCENT_COLOR)

        lines = [
            (f"Round {round_num} of {total}", SECONDARY_COLOR, 36, False),
            (name, TEXT_COLOR, 72, True),
            (room, SECONDARY_COLOR, 40, False),
            (difficulty.upper(), diff_color, 32, True),
        ]

        img = self._render_card_image(lines, theme_color)
        png_path = self.video_dir / f"mission_{key}.png"
        img.save(str(png_path))

        self._png_to_mp4(str(png_path), str(mp4_path), audio_path)
        return str(mp4_path)

    def generate_text_card(
        self,
        text: str,
        subtitle: str = "",
        theme_color: tuple = ACCENT_COLOR,
        audio_path: str | None = None,
    ) -> str:
        """Generate a text card MP4. Returns path to the video file."""
        key = self._cache_key("text", text, subtitle, str(audio_path or ""))
        mp4_path = self.video_dir / f"text_{key}.mp4"
        if mp4_path.exists():
            return str(mp4_path)

        # Word-wrap long text
        wrapped = textwrap.fill(text, width=35)
        lines = [(wrapped, TEXT_COLOR, 56, True)]
        if subtitle:
            lines.append((subtitle, SECONDARY_COLOR, 32, False))

        img = self._render_card_image(lines, theme_color)
        png_path = self.video_dir / f"text_{key}.png"
        img.save(str(png_path))

        self._png_to_mp4(str(png_path), str(mp4_path), audio_path)
        return str(mp4_path)

    def generate_silent_card(
        self,
        text: str,
        theme_color: tuple = ACCENT_COLOR,
        duration: float = 10.0,
    ) -> str:
        """Generate a silent card MP4 with a fixed duration."""
        key = self._cache_key("silent", text, str(duration))
        mp4_path = self.video_dir / f"silent_{key}.mp4"
        if mp4_path.exists():
            return str(mp4_path)

        wrapped = textwrap.fill(text, width=35)
        lines = [(wrapped, TEXT_COLOR, 56, True)]
        img = self._render_card_image(lines, theme_color)
        png_path = self.video_dir / f"silent_{key}.png"
        img.save(str(png_path))

        self._png_to_mp4(str(png_path), str(mp4_path), audio_path=None, duration=duration)
        return str(mp4_path)

    def _png_to_mp4(
        self,
        png_path: str,
        mp4_path: str,
        audio_path: str | None = None,
        duration: float | None = None,
    ):
        """Convert a PNG (+ optional audio) to an MP4 via ffmpeg."""
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", png_path]

        if audio_path:
            cmd += ["-i", audio_path]
            cmd += [
                "-c:v", "libx264", "-tune", "stillimage",
                "-c:a", "aac", "-b:a", "128k",
                "-pix_fmt", "yuv420p",
                "-shortest",
            ]
        else:
            d = duration or 10.0
            cmd += [
                "-t", str(d),
                "-c:v", "libx264", "-tune", "stillimage",
                "-pix_fmt", "yuv420p",
                "-an",
            ]

        cmd.append(mp4_path)

        logger.info(f"ffmpeg: generating {mp4_path}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error(f"ffmpeg error: {result.stderr[:500]}")
                raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")
            logger.info(f"Video card generated: {mp4_path}")
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg timed out")
            raise RuntimeError("ffmpeg timed out generating video card")
