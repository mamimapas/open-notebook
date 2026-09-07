import asyncio
import time
from pathlib import Path

import numpy as np
import pytest

import chatterbox_tts_adapter as adapter


def test_split_text_is_lossless_and_bounded():
    samples = [
        "Hola, ¿cómo estás? Esto es una prueba con signos españoles.",
        ("Una frase razonablemente larga. " * 80).strip(),
        "x" * 721,
        "URL https://example.com/ruta?uno=1&dos=2 y final.",
    ]
    for text in samples:
        chunks = adapter.split_text_lossless(text, 300)
        assert "".join(chunks) == text
        assert chunks
        assert all(0 < len(chunk) <= 300 for chunk in chunks)


@pytest.mark.parametrize(
    ("voice", "expected"),
    [
        ("presentadora", "female"),
        ("elena", "female"),
        ("es-ES-ElviraNeural", "female"),
        ("presentador", "male"),
        ("daniel", "male"),
        ("es-ES-AlvaroNeural", "male"),
    ],
)
def test_voice_aliases_resolve_to_two_new_es_es_profiles(voice, expected):
    profile = adapter.resolve_voice_profile(voice)
    assert profile.key == expected
    assert profile.locale == "es-ES"
    assert "AlvaroNeural" not in profile.reference_url
    assert "ElviraNeural" not in profile.reference_url


def test_empty_and_oversized_input_are_rejected():
    with pytest.raises(ValueError, match="vacío"):
        adapter.validate_input("   ", 20_000)
    with pytest.raises(ValueError, match="20,000"):
        adapter.validate_input("x" * 20_001, 20_000)


def test_candidate_failure_uses_edge_fallback(tmp_path, monkeypatch):
    async def broken_candidate(*_args, **_kwargs):
        raise TimeoutError("candidate timeout")

    async def working_edge(text, voice, speed, output_path):
        assert text == "Texto completo"
        assert voice == "es-ES-AlvaroNeural"
        Path(output_path).write_bytes(b"ID3fallback-audio")

    monkeypatch.setattr(adapter, "synthesize_candidate", broken_candidate)
    monkeypatch.setattr(adapter, "synthesize_edge", working_edge)
    result = asyncio.run(
        adapter.synthesize_with_fallback(
            text="Texto completo",
            voice="presentador",
            speed=1.0,
            response_format="mp3",
            workdir=tmp_path,
        )
    )
    assert result.engine == "edge-tts"
    assert result.fallback_reason == "TimeoutError: candidate timeout"
    assert result.path.read_bytes().startswith(b"ID3")


def test_empty_candidate_output_uses_fallback(tmp_path, monkeypatch):
    async def empty_candidate(_text, _profile, _speed, output_path):
        Path(output_path).touch()

    async def working_edge(_text, _voice, _speed, output_path):
        Path(output_path).write_bytes(b"RIFF\x10\x00\x00\x00WAVE")

    monkeypatch.setattr(adapter, "synthesize_candidate", empty_candidate)
    monkeypatch.setattr(adapter, "synthesize_edge", working_edge)
    result = asyncio.run(
        adapter.synthesize_with_fallback(
            "Texto", "presentadora", 1.0, "wav", tmp_path
        )
    )
    assert result.engine == "edge-tts"
    assert "empty output" in result.fallback_reason


def test_benchmark_decision_is_fail_closed():
    assert adapter.benchmark_decision(1.49, True, True) == "PROMOTE_CANDIDATE"
    assert adapter.benchmark_decision(1.51, True, True) == "KEEP_CURRENT"
    assert adapter.benchmark_decision(1.0, False, True) == "KEEP_CURRENT"
    assert adapter.benchmark_decision(None, True, True) == "BLOCKED"


def test_audio_validation_rejects_wrong_container_signature(tmp_path):
    fake_mp3 = tmp_path / "fake.mp3"
    fake_mp3.write_bytes(b"not-an-mp3-file")
    fake_wav = tmp_path / "fake.wav"
    fake_wav.write_bytes(b"RIFF\x10\x00\x00\x00NOPE")
    assert adapter._valid_audio(fake_mp3) is False
    assert adapter._valid_audio(fake_wav) is False


def test_candidate_timeout_keeps_worker_output_isolated(tmp_path, monkeypatch):
    isolated = tmp_path / "isolated"

    def slow_candidate(_text, _profile, _speed, output_path):
        time.sleep(0.04)
        Path(output_path).write_bytes(b"ID3late-audio")

    monkeypatch.setattr(adapter.tempfile, "mkdtemp", lambda **_kwargs: str(isolated))
    monkeypatch.setattr(adapter, "_candidate_sync", slow_candidate)
    monkeypatch.setattr(adapter, "CANDIDATE_TIMEOUT", 0.005)
    target = tmp_path / "response" / "speech.mp3"
    with pytest.raises(TimeoutError):
        asyncio.run(
            adapter.synthesize_candidate(
                "Texto", adapter.FEMALE, 1.0, target
            )
        )
    time.sleep(0.08)
    assert not isolated.exists()
    assert not target.exists()


def test_model_waveform_is_normalized_to_one_mono_sample_axis():
    waveform = np.arange(12, dtype=np.float32).reshape(1, 12)
    samples = adapter._mono_samples(waveform)
    assert samples.shape == (12,)
    with pytest.raises(RuntimeError, match="shape inválida"):
        adapter._mono_samples(np.empty((0,), dtype=np.float32))
