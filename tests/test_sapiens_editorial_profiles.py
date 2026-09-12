import json
from pathlib import Path

from tools.reconcile_sapiens_editorial_profiles import build_payloads


def test_perfiles_editoriales_heredan_modelos_y_voces_sin_tocar_largo():
    root = Path(__file__).parents[1]
    contract = json.loads((root / "config" / "sapiens_editorial_profiles.json").read_text())
    base = {
        "outline_llm": "model:outline", "transcript_llm": "model:transcript",
        "speaker_config": "speaker_profile:sapiens-dueto",
    }
    payloads = build_payloads(contract, base)
    assert [row["name"] for row in payloads] == [
        "sapiens_papers", "sapiens_noticias_ia", "sapiens_noticias_reales",
    ]
    assert all(row["speaker_config"] == "speaker_profile:sapiens-dueto" for row in payloads)
    assert contract["expected_voices"] == ["es-ES-AlvaroNeural", "es-ES-ElviraNeural"]
    assert "sapiens_largo" not in {row["name"] for row in payloads}
