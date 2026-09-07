import json

from benchmark_chatterbox_tts import fallback_proof_is_pass


def test_fallback_proof_requires_real_edge_audio(tmp_path):
    proof = tmp_path / "fallback.json"
    proof.write_text(
        json.dumps(
            {
                "fallback": {
                    "status": "PASS",
                    "engine": "edge-tts",
                    "http_status": 200,
                    "bytes": 20880,
                }
            }
        ),
        encoding="utf-8",
    )
    assert fallback_proof_is_pass(proof) is True


def test_fallback_proof_is_fail_closed(tmp_path):
    missing = tmp_path / "missing.json"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("not-json", encoding="utf-8")
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"fallback": {"status": "PASS"}}), encoding="utf-8")
    assert fallback_proof_is_pass(None) is False
    assert fallback_proof_is_pass(missing) is False
    assert fallback_proof_is_pass(malformed) is False
    assert fallback_proof_is_pass(incomplete) is False
