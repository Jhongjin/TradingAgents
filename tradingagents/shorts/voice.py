"""Narration: speak each scene's line locally, then fit the cut to the speech.

The voice runs on this machine through VoxCPM, which lives in its own virtual
environment with its own torch build, so it is driven as a subprocess rather
than imported. Nothing is sent anywhere.

The important part is the order. Speech is generated first and measured, and
then each scene is stretched to hold its own line, so the words and the picture
cannot drift apart. A scene never shrinks below the duration it was authored
with, because some shots need to be held whatever the narrator does.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from .stories import Storyboard

VOXCPM_HOME_ENV = "TRADINGAGENTS_VOXCPM_HOME"
VOXCPM_PYTHON_ENV = "TRADINGAGENTS_VOXCPM_PYTHON"
VOICE_REF_ENV = "TRADINGAGENTS_SHORTS_VOICE_REF"
DEFAULT_HOME = Path("D:/AI/VoxCPM2")
TAIL_SECONDS = 0.55      # the breath left after a line before the scene turns
LEAD_SECONDS = 0.2       # and the beat before it starts


class VoiceUnavailableError(RuntimeError):
    """No local VoxCPM to speak with, so the cut stays silent."""


@dataclass(frozen=True)
class Narration:
    track: Path
    board: Storyboard
    lines: tuple[dict, ...]

    @property
    def seconds(self) -> float:
        return self.board.seconds


def voxcpm_home() -> Path:
    return Path(os.getenv(VOXCPM_HOME_ENV) or DEFAULT_HOME)


def voxcpm_python() -> Path | None:
    override = (os.getenv(VOXCPM_PYTHON_ENV) or "").strip()
    if override:
        return Path(override) if Path(override).exists() else None
    candidate = voxcpm_home() / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return candidate
    candidate = voxcpm_home() / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def voice_reference() -> Path | None:
    """The one voice the channel speaks in, if a reference has been frozen."""

    raw = (os.getenv(VOICE_REF_ENV) or "").strip()
    if raw:
        return Path(raw) if Path(raw).exists() else None
    default = Path("assets/voice/narrator.wav")
    return default if default.exists() else None


def reference_text(reference: Path | None = None) -> str | None:
    """What is said in the reference clip, read from the .txt beside it.

    VoxCPM clones a voice far more closely when it is told what the prompt
    audio says, so the transcript travels with the wav.
    """

    source = reference or voice_reference()
    if source is None:
        return None
    beside = source.with_suffix(".txt")
    if not beside.exists():
        return None
    text = " ".join(beside.read_text(encoding="utf-8").split())
    return text or None


def available() -> bool:
    return voxcpm_python() is not None and (voxcpm_home() / "models" / "VoxCPM2").exists()


def speak(lines: Sequence[dict], out_dir: Path, *, reference: Path | None = None, prompt_text: str | None = None, device: str = "cuda") -> dict:
    """Synthesize one wav per line and return the manifest VoxCPM wrote."""

    python = voxcpm_python()
    if python is None:
        raise VoiceUnavailableError(
            f"VoxCPM 을 찾지 못했습니다. {VOXCPM_HOME_ENV} 또는 {VOXCPM_PYTHON_ENV} 를 설정해 주세요."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cached = _cached(lines, out_dir, reference, prompt_text)
    if cached is not None:
        return cached
    job = {
        "model": str(voxcpm_home() / "models" / "VoxCPM2"),
        "out_dir": str(out_dir),
        "reference": str(reference) if reference else None,
        "reference_text": prompt_text,
        "device": device,
        "lines": [dict(line) for line in lines],
    }
    job_path = out_dir / "job.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "voxcpm_narrate.py"
    result = subprocess.run([str(python), str(script), str(job_path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise VoiceUnavailableError(f"VoxCPM 실패 ({result.returncode}): {(result.stderr or '')[-600:]}")
    return json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))


def _cached(lines: Sequence[dict], out_dir: Path, reference: Path | None, prompt_text: str | None = None) -> dict | None:
    """Reuse the last take when the words and the voice have not changed."""

    manifest_path = out_dir / "manifest.json"
    job_path = out_dir / "job.json"
    if not (manifest_path.exists() and job_path.exists()):
        return None
    try:
        previous = json.loads(job_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    same_text = [(item["id"], item["text"]) for item in previous.get("lines") or []] == [(item["id"], item["text"]) for item in lines]
    same_voice = (previous.get("reference") or None) == (str(reference) if reference else None) and (previous.get("reference_text") or None) == (prompt_text or None)
    if not (same_text and same_voice):
        return None
    if not all(Path(item["path"]).exists() for item in manifest.get("lines") or []):
        return None
    return manifest


def fit(board: Storyboard, manifest: dict) -> tuple[Storyboard, list[dict]]:
    """Stretch each scene to hold its line, and say where each line starts."""

    spoken = {item["id"]: item for item in manifest.get("lines") or []}
    scenes = []
    placed: list[dict] = []
    cursor = 0.0
    for index, scene in enumerate(board.scenes):
        line = spoken.get(f"s{index}")
        seconds = scene.seconds
        if line:
            seconds = max(seconds, LEAD_SECONDS + float(line["seconds"]) + TAIL_SECONDS)
            placed.append({"start": cursor + LEAD_SECONDS, "path": line["path"], "seconds": float(line["seconds"])})
        scenes.append(replace(scene, seconds=seconds))
        cursor += seconds
    return replace(board, scenes=tuple(scenes)), placed


def mix_track(placed: Sequence[dict], total: float, target: Path, *, music: Path | None = None) -> Path:
    """Lay each spoken line at its own second, over an optional music bed."""

    binary = shutil.which("ffmpeg")
    if binary is None:
        raise VoiceUnavailableError("ffmpeg 를 찾지 못했습니다.")
    target.parent.mkdir(parents=True, exist_ok=True)

    command = [binary, "-y", "-loglevel", "error"]
    filters = []
    labels = []
    for index, item in enumerate(placed):
        command += ["-i", str(item["path"])]
        delay = int(round(float(item["start"]) * 1000))
        filters.append(f"[{index}:a]aresample=48000,adelay={delay}|{delay}[v{index}]")
        labels.append(f"[v{index}]")
    if music is not None:
        position = len(placed)
        command += ["-i", str(music)]
        # under the voice, and out before the end, so the last word is not stepped on
        filters.append(f"[{position}:a]aresample=48000,volume=0.16,afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5[bed]")
        labels.append("[bed]")
    filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mixed]")
    filters.append(f"[mixed]apad,atrim=0:{total:.3f},alimiter=limit=0.95[out]")
    command += ["-filter_complex", ";".join(filters), "-map", "[out]", "-ac", "2", "-ar", "48000", str(target)]

    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise VoiceUnavailableError(f"오디오 합성 실패: {(result.stderr or '')[-600:]}")
    return target


def narrate(board: Storyboard, *, work_dir: Path | None = None, music: Path | None = None, device: str = "cuda") -> Narration:
    """Speak the board, fit it to the speech, and hand back a track to mux."""

    lines = [
        {"id": f"s{index}", "text": scene.narration.strip()}
        for index, scene in enumerate(board.scenes)
        if (scene.narration or "").strip()
    ]
    if not lines:
        raise VoiceUnavailableError("읽을 내레이션이 없습니다.")

    root = Path(work_dir or Path(tempfile.gettempdir()) / "tradingagents-shorts" / board.slug)
    reference = voice_reference()
    manifest = speak(lines, root, reference=reference, prompt_text=reference_text(reference), device=device)
    fitted, placed = fit(board, manifest)
    track = mix_track(placed, fitted.seconds, root / "narration.wav", music=music)
    return Narration(track=track, board=fitted, lines=tuple(placed))


__all__ = [
    "Narration", "VoiceUnavailableError", "available", "fit", "mix_track",
    "narrate", "reference_text", "speak", "voice_reference", "voxcpm_home", "voxcpm_python",
]
