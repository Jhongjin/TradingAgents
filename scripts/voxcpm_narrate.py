"""Speak the narration lines with a local VoxCPM, one wav per line.

This runs inside VoxCPM's own virtual environment, which is the only place the
model and its torch build live, so the project never has to carry them. It
takes one JSON job on the command line and writes a manifest beside the wavs:

    python scripts/voxcpm_narrate.py job.json

Job shape::

    {"model": "...", "out_dir": "...", "reference": "...|null",
     "reference_text": "...|null", "device": "cuda",
     "lines": [{"id": "hook", "text": "..."}]}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    root = Path(job["model"]).resolve().parent.parent
    os.environ.setdefault("HF_HOME", str(root / "cache" / "huggingface"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(root / "cache" / "modelscope"))

    import numpy as np
    import soundfile as sf

    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass

    from voxcpm import VoxCPM

    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    model = VoxCPM.from_pretrained(
        job["model"],
        load_denoiser=False,
        local_files_only=True,
        optimize=False,
        device=job.get("device") or "cuda",
    )
    sample_rate = model.tts_model.sample_rate

    # The same reference on every line is what keeps one channel sounding like
    # one narrator; without it each call invents a different speaker.
    shared = {}
    reference = job.get("reference")
    if reference and Path(reference).exists():
        shared["reference_wav_path"] = reference
        if job.get("reference_text"):
            shared["prompt_wav_path"] = reference
            shared["prompt_text"] = job["reference_text"]

    manifest = []
    for line in job["lines"]:
        target = out_dir / f"{line['id']}.wav"
        audio = np.asarray(
            model.generate(
                text=line["text"],
                cfg_value=float(job.get("cfg", 2.0)),
                inference_timesteps=int(job.get("timesteps", 10)),
                normalize=False,
                denoise=False,
                retry_badcase=True,
                retry_badcase_max_times=3,
                **shared,
            ),
            dtype=np.float32,
        ).squeeze()
        sf.write(str(target), audio, sample_rate)
        manifest.append({"id": line["id"], "path": str(target), "seconds": len(audio) / sample_rate, "text": line["text"]})
        print(f"{line['id']} {len(audio) / sample_rate:.2f}s", flush=True)

    (out_dir / "manifest.json").write_text(
        json.dumps({"sample_rate": sample_rate, "lines": manifest}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
