"""Compare Edge and Chatterbox adapters and emit a fail-closed JSON receipt."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

SCRIPT = (
    "La inteligencia artificial generativa continúa avanzando, pero debemos separar "
    "la novedad técnica del ruido. Una medición convincente sólo es útil cuando puede "
    "repetirse bajo las mismas condiciones y deja evidencia verificable del resultado."
)


def probe(base_url: str, voice: str, output: Path) -> dict:
    started = time.perf_counter()
    with httpx.Client(timeout=240) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/v1/audio/speech",
            json={
                "model": "benchmark",
                "input": SCRIPT,
                "voice": voice,
                "response_format": "mp3",
                "speed": 1.0,
            },
        )
    wall = time.perf_counter() - started
    response.raise_for_status()
    output.write_bytes(response.content)
    return {
        "wall_seconds": round(wall, 3),
        "bytes": len(response.content),
        "engine": response.headers.get("x-tts-engine"),
        "fallback": response.headers.get("x-tts-fallback"),
    }


def fallback_proof_is_pass(path: Path | None) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    fallback = receipt.get("fallback", receipt)
    return (
        fallback.get("status") == "PASS"
        and fallback.get("engine") == "edge-tts"
        and fallback.get("http_status") == 200
        and int(fallback.get("bytes", 0)) > 0
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge", default="http://localhost:7998")
    parser.add_argument("--candidate", default="http://localhost:7999")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quality-accepted", action="store_true")
    parser.add_argument(
        "--fallback-proof",
        type=Path,
        help="JSON receipt from a deliberately induced candidate failure",
    )
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"status": "BLOCKED", "quality_accepted": args.quality_accepted}
    try:
        edge = probe(args.edge, "presentadora", args.out.with_suffix(".edge.mp3"))
        candidate = probe(
            args.candidate, "presentadora", args.out.with_suffix(".candidate.mp3")
        )
        ratio = candidate["wall_seconds"] / max(edge["wall_seconds"], 0.001)
        fallback_verified = fallback_proof_is_pass(args.fallback_proof)
        decision = (
            "PROMOTE_CANDIDATE"
            if args.quality_accepted
            and fallback_verified
            and candidate["engine"] == "chatterbox-es-es"
            and ratio <= 1.5
            else "KEEP_CURRENT"
        )
        receipt.update(
            status=decision,
            edge=edge,
            candidate=candidate,
            tts_wall_ratio=round(ratio, 3),
            fallback_verified=fallback_verified,
        )
    except Exception as exc:
        receipt.update(error=f"{type(exc).__name__}: {exc}")
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["status"] in {"PROMOTE_CANDIDATE", "KEEP_CURRENT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
