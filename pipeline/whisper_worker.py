#!/usr/bin/env python3
"""Standalone local Whisper worker for clip subtitle fallback.

Run this with a Python environment that has ``openai-whisper`` installed.  The
pipeline's default ``.venv`` does not include torch/whisper; it can point at the
sibling v2-automation venv with ``PIPELINE_WHISPER_PYTHON``.

stdout: one JSON object with ``segments``, ``language``, ``model``.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="whisper_worker.py")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", default="base")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()
    try:
        import torch
        import whisper
    except ImportError as error:
        print(json.dumps({"segments": [], "error": f"whisper import failed: {error}"}))
        return 1
    try:
        model = whisper.load_model(args.model)
        fp16 = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
        result = model.transcribe(
            args.audio,
            language=args.language or None,
            fp16=fp16,
            verbose=False,
        )
        segments = []
        for segment in result.get("segments", []):
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start": float(segment.get("start") or 0.0),
                    "end": float(segment.get("end") or 0.0),
                    "text": text,
                }
            )
        print(
            json.dumps(
                {
                    "segments": segments,
                    "language": result.get("language"),
                    "model": args.model,
                    "error": None,
                }
            )
        )
        return 0
    except Exception as error:  # noqa: BLE001
        print(json.dumps({"segments": [], "error": f"{type(error).__name__}: {error}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
