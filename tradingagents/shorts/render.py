"""Storyboard to file: frames into ffmpeg, and the text that goes with them.

Frames are painted one at a time and piped straight to the encoder, so a
thirty second cut needs no scratch directory and no intermediate images. The
poster is simply the frame at a chosen second, which is what the thumbnail and
any still preview should be.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from PIL import Image

from .design import ACCENT, FPS, HEIGHT, LINE, MARGIN, MUTED, WIDTH, Canvas
from .scenes import Scene
from .stories import Storyboard


class FfmpegMissingError(RuntimeError):
    """Frames can be painted without ffmpeg, but nothing can be encoded."""


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def scene_at(scenes: tuple[Scene, ...], seconds: float) -> tuple[Scene, float] | None:
    """Which scene is on screen at that moment, and how far into it we are."""

    cursor = 0.0
    for scene in scenes:
        if seconds < cursor + scene.seconds:
            return scene, seconds - cursor
        cursor += scene.seconds
    return (scenes[-1], scenes[-1].seconds) if scenes else None


def chrome(canvas: Canvas, board: Storyboard, seconds: float, *, watermark: str) -> None:
    """The two marks that never leave: a progress line, and where this is from.

    A viewer who cannot see how much is left assumes it is long and scrolls,
    so the line at the top is worth its two pixels. The watermark carries the
    address through every frame, including the ones people screenshot.
    """

    total = max(board.seconds, 0.001)
    canvas.rule(186, x0=MARGIN, x1=WIDTH - MARGIN, colour=LINE, alpha=0.7)
    progress = max(0.0, min(1.0, seconds / total))
    if progress > 0:
        canvas.draw.rectangle((MARGIN, 186, MARGIN + progress * (WIDTH - MARGIN * 2), 188), fill=ACCENT)
    if watermark:
        canvas.text((WIDTH - MARGIN, 1512), watermark, size=30, fill=MUTED, anchor="ra", alpha=0.85)


def paint(board: Storyboard, seconds: float, *, watermark: str | None = None) -> Image.Image:
    """The single frame at that moment of the cut."""

    canvas = Canvas.blank()
    found = scene_at(board.scenes, seconds)
    if found is not None:
        scene, local = found
        scene.draw(canvas, local)
    chrome(canvas, board, seconds, watermark=_watermark(watermark))
    return canvas.image


def _watermark(value: str | None) -> str:
    if value is not None:
        return value
    from .stories import site_url

    return site_url().split("://", 1)[-1]


def frames(board: Storyboard, *, fps: int = FPS, watermark: str | None = None) -> Iterator[Image.Image]:
    total = max(1, int(round(board.seconds * fps)))
    for index in range(total):
        yield paint(board, index / fps, watermark=watermark)


@dataclass(frozen=True)
class Rendered:
    video: Path
    poster: Path
    caption: Path
    seconds: float
    frame_count: int


def write_poster(board: Storyboard, target: Path, *, at: float = 1.8, watermark: str | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    paint(board, min(at, max(board.seconds - 0.1, 0.0)), watermark=watermark).save(target, format="PNG", optimize=True)
    return target


def write_caption(board: Storyboard, target: Path) -> Path:
    """Title, description and tags, ready to paste into the upload form."""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            (
                board.title,
                "",
                board.description,
                "",
                "태그: " + ", ".join(board.tags),
                f"길이: {board.seconds:.1f}초 · {WIDTH}x{HEIGHT} · {FPS}fps",
            )
        ),
        encoding="utf-8",
    )
    return target


def render(
    board: Storyboard,
    target: Path,
    *,
    fps: int = FPS,
    crf: int = 20,
    poster_at: float = 1.8,
    audio: Path | None = None,
    watermark: str | None = None,
) -> Rendered:
    """Encode the cut, and write the poster and the caption beside it."""

    binary = ffmpeg_path()
    if binary is None:
        raise FfmpegMissingError("ffmpeg 를 찾지 못했습니다. 설치 후 PATH 에 추가해 주세요.")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    command = [
        binary, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(fps),
        "-i", "-",
    ]
    if audio is not None:
        # trimmed to the video and faded out, so a long track does not run past the end
        command += ["-i", str(audio), "-shortest", "-c:a", "aac", "-b:a", "128k",
                    "-af", f"afade=t=out:st={max(board.seconds - 1.2, 0):.2f}:d=1.2,volume=0.55"]
    command += [
        # yuv420p and faststart are what make the file play everywhere and
        # start without downloading the whole thing first.
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(target),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    count = 0
    assert process.stdin is not None
    try:
        for frame in frames(board, fps=fps, watermark=watermark):
            process.stdin.write(frame.tobytes())
            count += 1
    finally:
        process.stdin.close()
        code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg 가 {code} 로 종료했습니다")

    poster = write_poster(board, target.with_suffix(".png"), at=poster_at, watermark=watermark)
    caption = write_caption(board, target.with_suffix(".txt"))
    return Rendered(video=target, poster=poster, caption=caption, seconds=board.seconds, frame_count=count)


__all__ = ["FfmpegMissingError", "Rendered", "chrome", "ffmpeg_path", "frames", "paint", "render", "scene_at", "write_caption", "write_poster"]
