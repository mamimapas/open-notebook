"""Reconcilia perfiles editoriales sin borrar ni modificar sapiens_largo/sapiens_dueto."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "sapiens_editorial_profiles.json"


def _request(base: str, method: str, path: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def build_payloads(contract: dict, base_profile: dict) -> list[dict]:
    required = ("outline_llm", "transcript_llm")
    if any(not base_profile.get(field) for field in required):
        raise ValueError("sapiens_largo no tiene modelos resolubles")
    return [{
        "name": profile["name"],
        "description": profile["description"],
        "speaker_config": base_profile["speaker_config"],
        "outline_llm": base_profile["outline_llm"],
        "transcript_llm": base_profile["transcript_llm"],
        "language": profile["language"],
        "default_briefing": profile["default_briefing"],
        "num_segments": profile["num_segments"],
    } for profile in contract["profiles"]]


def reconcile(base: str, apply: bool) -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    profiles = _request(base, "GET", "/api/episode-profiles")
    by_name = {row["name"]: row for row in profiles}
    base_profile = by_name.get(contract["base_profile"])
    if not base_profile:
        raise ValueError("sapiens_largo ausente; no se puede heredar su configuración")
    speaker = _request(base, "GET", f"/api/speaker-profiles/{contract['speaker_profile']}")
    voices = {str(row.get("voice_id") or "") for row in speaker.get("speakers", [])}
    if not set(contract["expected_voices"]).issubset(voices):
        raise ValueError("sapiens_dueto no conserva Álvaro y Elvira de español de España")
    actions = []
    for payload in build_payloads(contract, base_profile):
        existing = by_name.get(payload["name"])
        method = "PUT" if existing else "POST"
        path = f"/api/episode-profiles/{existing['id']}" if existing else "/api/episode-profiles"
        actions.append({"name": payload["name"], "method": method, "path": path})
        if apply:
            readback = _request(base, method, path, payload)
            for key, value in payload.items():
                if readback.get(key) != value:
                    raise ValueError(f"readback divergente en {payload['name']}:{key}")
    return {"status": "PASS", "applied": apply, "actions": actions, "contract": contract["schema_version"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("OPEN_NOTEBOOK_API_URL", "http://localhost:5055"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(reconcile(args.base_url, args.apply), ensure_ascii=False))
        return 0
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
