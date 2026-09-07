"""OpenAI-compatible Chatterbox es-ES adapter with a bounded Edge fallback.

The candidate is the official Spain-Spanish single-language checkpoint.  Model
weights and reference audio are cached outside the repository.  Arbitrary voice
cloning is intentionally not exposed: callers can only select the two reviewed
editorial voices.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import edge_tts
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatterbox-es-es")

PORT = int(os.environ.get("TTS_PORT", "7999"))
MAX_INPUT_CHARS = int(os.environ.get("TTS_MAX_INPUT_CHARS", "20000"))
MAX_CHUNK_CHARS = int(os.environ.get("TTS_MAX_CHUNK_CHARS", "300"))
CANDIDATE_TIMEOUT = float(os.environ.get("TTS_CANDIDATE_TIMEOUT_SECONDS", "180"))
MODEL_ROOT = Path(os.environ.get("CHATTERBOX_MODEL_ROOT", "/models"))
SOURCE_DIR = Path(
    os.environ.get("CHATTERBOX_SOURCE_DIR", "/opt/chatterbox-space/chatterbox/src")
)
FFMPEG = os.environ.get("FFMPEG_BINARY", "ffmpeg")


@dataclass(frozen=True)
class VoiceProfile:
    key: Literal["female", "male"]
    locale: str
    reference_url: str
    reference_sha256: str
    edge_voice: str


@dataclass(frozen=True)
class SynthesisResult:
    path: Path
    engine: str
    fallback_reason: str | None
    wall_seconds: float


FEMALE = VoiceProfile(
    key="female",
    locale="es-ES",
    reference_url=(
        "https://storage.googleapis.com/chatterbox-demo-samples/"
        "mtl-v3-single-language-prompts/es-es/es_es_f1.wav"
    ),
    reference_sha256="61853caa5cd0fbf91ac2448c39bff35b46fa9160340b1e6bc47d62fd94746bfa",
    edge_voice="es-ES-ElviraNeural",
)
MALE = VoiceProfile(
    key="male",
    locale="es-ES",
    reference_url=(
        "https://storage.googleapis.com/chatterbox-demo-samples/"
        "mtl_prompts/es_m1.flac"
    ),
    reference_sha256="fa07f3ce88bda9b64fbe5e699bdbc9a966255e981ee41cf6ef15f401c790c27d",
    edge_voice="es-ES-AlvaroNeural",
)

_FEMALE_ALIASES = {
    "presentadora", "female", "woman", "mujer", "elena", "elvira",
    "shimmer", "nova", "coral", "sage", "es-es-elviraneural",
}
_MALE_ALIASES = {
    "presentador", "male", "man", "hombre", "daniel", "alvaro",
    "echo", "onyx", "ash", "alloy", "fable", "es-es-alvaroneural",
}

_MODEL = None
_MODEL_LOCK = threading.Lock()
_HEAVY_SEMAPHORE = asyncio.Semaphore(1)
_CANDIDATE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="chatterbox-cpu"
)
_CANDIDATE_IN_FLIGHT = threading.Event()
_STATE_LOCK = threading.Lock()
_STATE = {
    "last_engine": None,
    "last_fallback_reason": None,
    "last_wall_seconds": None,
}


class SpeechRequest(BaseModel):
    input: str
    model: str = "chatterbox-es-es"
    voice: str = "presentadora"
    response_format: Literal["mp3", "wav"] = "mp3"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def validate_input(text: str, max_chars: int = MAX_INPUT_CHARS) -> str:
    if not text or not text.strip():
        raise ValueError("El texto no puede estar vacío")
    if len(text) > max_chars:
        raise ValueError(f"El texto supera el límite de {max_chars:,} caracteres")
    return text


def split_text_lossless(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on nearby natural boundaries while preserving every input byte."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if not text:
        return []
    chunks: list[str] = []
    cursor = 0
    natural = ".!?;:,\n\r\t "
    minimum_preferred = max(1, max_chars // 2)
    while cursor < len(text):
        remaining = len(text) - cursor
        if remaining <= max_chars:
            chunks.append(text[cursor:])
            break
        end = cursor + max_chars
        cut = None
        for index in range(end - 1, cursor + minimum_preferred - 1, -1):
            if text[index] in natural:
                cut = index + 1
                break
        if cut is None:
            cut = end
        chunks.append(text[cursor:cut])
        cursor = cut
    return chunks


def resolve_voice_profile(voice: str | None) -> VoiceProfile:
    normalized = (voice or "presentadora").strip().lower()
    if normalized in _MALE_ALIASES:
        return MALE
    if normalized in _FEMALE_ALIASES:
        return FEMALE
    raise ValueError(f"Voz no permitida: {voice}")


def benchmark_decision(
    end_to_end_ratio: float | None,
    quality_accepted: bool,
    fallback_verified: bool,
) -> str:
    if end_to_end_ratio is None:
        return "BLOCKED"
    if quality_accepted and fallback_verified and end_to_end_ratio <= 1.5:
        return "PROMOTE_CANDIDATE"
    return "KEEP_CURRENT"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reference_path(profile: VoiceProfile) -> Path:
    suffix = Path(profile.reference_url).suffix
    target = MODEL_ROOT / "voices" / f"{profile.key}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and _sha256(target) == profile.reference_sha256:
        return target
    temporary = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(profile.reference_url, temporary)
    if _sha256(temporary) != profile.reference_sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"checksum inválido para la voz {profile.key}")
    temporary.replace(target)
    return target


def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        if not SOURCE_DIR.is_dir():
            raise RuntimeError(f"Chatterbox source no encontrado: {SOURCE_DIR}")
        source = str(SOURCE_DIR)
        if source not in sys.path:
            sys.path.insert(0, source)
        from chatterbox.tts import ChatterboxTTS

        logger.info("Cargando Chatterbox es-ES en CPU")
        _MODEL = ChatterboxTTS.from_pretrained("cpu")
        return _MODEL


def _run_ffmpeg(inputs: list[Path], output: Path, speed: float) -> None:
    concat_file = output.parent / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in inputs), encoding="utf-8"
    )
    codec = ["-codec:a", "libmp3lame", "-b:a", "192k"] if output.suffix == ".mp3" else ["-codec:a", "pcm_s16le"]
    command = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
        "-safe", "0", "-i", str(concat_file), "-filter:a", f"atempo={speed}",
        *codec, str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg falló: {completed.stderr[-300:]}")


def _mono_samples(audio):
    """Convert the model's [channel, samples] tensor into soundfile's vector."""
    import numpy as np

    if hasattr(audio, "detach"):
        audio = audio.detach()
    if hasattr(audio, "cpu"):
        audio = audio.cpu()
    if hasattr(audio, "numpy"):
        audio = audio.numpy()
    samples = np.asarray(audio).squeeze()
    if samples.ndim != 1 or samples.size == 0:
        raise RuntimeError(f"candidate waveform shape inválida: {samples.shape}")
    return samples


def _candidate_sync(
    text: str,
    profile: VoiceProfile,
    speed: float,
    output_path: Path,
) -> None:
    import soundfile as sf

    model = _load_model()
    reference = _reference_path(profile)
    chunk_paths: list[Path] = []
    for index, chunk in enumerate(split_text_lossless(text)):
        audio = model.generate(
            chunk,
            audio_prompt_path=str(reference),
            exaggeration=0.45,
            cfg_weight=0.45,
            temperature=0.75,
            language_id="es",
        )
        chunk_path = output_path.parent / f"candidate-{index:04d}.wav"
        sf.write(chunk_path, _mono_samples(audio), model.sr, format="WAV")
        chunk_paths.append(chunk_path)
    _run_ffmpeg(chunk_paths, output_path, speed)


async def synthesize_candidate(
    text: str,
    profile: VoiceProfile,
    speed: float,
    output_path: str | Path,
) -> None:
    async with _HEAVY_SEMAPHORE:
        if _CANDIDATE_IN_FLIGHT.is_set():
            raise RuntimeError("candidate inference still draining after timeout")
        target = Path(output_path)
        isolated_dir = Path(tempfile.mkdtemp(prefix="chatterbox-candidate-"))
        isolated_output = isolated_dir / f"speech{target.suffix}"
        _CANDIDATE_IN_FLIGHT.set()
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            _CANDIDATE_EXECUTOR,
            _candidate_sync,
            text,
            profile,
            speed,
            isolated_output,
        )
        future.add_done_callback(lambda _done: _CANDIDATE_IN_FLIGHT.clear())
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=CANDIDATE_TIMEOUT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(isolated_output, target)
        finally:
            if future.done():
                shutil.rmtree(isolated_dir, ignore_errors=True)
            else:
                future.add_done_callback(
                    lambda _done: shutil.rmtree(isolated_dir, ignore_errors=True)
                )


async def synthesize_edge(
    text: str,
    voice: str,
    speed: float,
    output_path: str | Path,
) -> None:
    target = Path(output_path)
    rate = f"{int(round((speed - 1.0) * 100)):+d}%"
    edge_mp3 = target if target.suffix == ".mp3" else target.with_suffix(".edge.mp3")
    await edge_tts.Communicate(text, voice, rate=rate).save(str(edge_mp3))
    if target.suffix == ".wav":
        _run_ffmpeg([edge_mp3], target, 1.0)


def _valid_audio(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 8:
        return False
    header = path.read_bytes()[:12]
    if path.suffix.lower() == ".wav":
        return header.startswith(b"RIFF") and header[8:12] == b"WAVE"
    if path.suffix.lower() == ".mp3":
        return header.startswith(b"ID3") or header[:2] in {
            b"\xff\xfb",
            b"\xff\xf3",
            b"\xff\xf2",
        }
    return False


async def synthesize_with_fallback(
    text: str,
    voice: str,
    speed: float,
    response_format: str,
    workdir: str | Path,
) -> SynthesisResult:
    validate_input(text)
    profile = resolve_voice_profile(voice)
    directory = Path(workdir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".wav" if response_format == "wav" else ".mp3"
    candidate_path = directory / f"speech-candidate{suffix}"
    started = time.perf_counter()
    fallback_reason = None
    try:
        await synthesize_candidate(text, profile, speed, candidate_path)
        if not _valid_audio(candidate_path):
            raise RuntimeError("candidate empty output")
        result = SynthesisResult(
            candidate_path, "chatterbox-es-es", None, time.perf_counter() - started
        )
    except Exception as exc:
        fallback_reason = f"{type(exc).__name__}: {exc}"[:240]
        logger.warning("Chatterbox degradado a Edge: %s", fallback_reason)
        fallback_path = directory / f"speech-fallback{suffix}"
        await synthesize_edge(text, profile.edge_voice, speed, fallback_path)
        if not _valid_audio(fallback_path):
            raise RuntimeError("fallback Edge produjo audio vacío") from exc
        result = SynthesisResult(
            fallback_path,
            "edge-tts",
            fallback_reason,
            time.perf_counter() - started,
        )
    with _STATE_LOCK:
        _STATE.update(
            last_engine=result.engine,
            last_fallback_reason=result.fallback_reason,
            last_wall_seconds=round(result.wall_seconds, 3),
        )
    return result


app = FastAPI(title="Chatterbox es-ES TTS Adapter")


@app.get("/health")
def health():
    with _STATE_LOCK:
        state = dict(_STATE)
    return {
        "status": "healthy",
        "candidate": "chatterbox-es-es-cpu",
        "fallback": "edge-tts",
        "locale": "es-ES",
        "voices": {"female": FEMALE.key, "male": MALE.key},
        "max_chunk_chars": MAX_CHUNK_CHARS,
        "max_input_chars": MAX_INPUT_CHARS,
        **state,
    }


@app.get("/v1/models")
def models():
    return {
        "object": "list",
        "data": [
            {"id": "chatterbox-es-es", "object": "model", "owned_by": "resemble-ai"}
        ],
    }


@app.post("/v1/audio/speech")
async def speech(request: SpeechRequest):
    try:
        validate_input(request.input)
        resolve_voice_profile(request.voice)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    directory = Path(tempfile.mkdtemp(prefix="chatterbox-es-es-"))
    try:
        result = await synthesize_with_fallback(
            request.input,
            request.voice,
            request.speed,
            request.response_format,
            directory,
        )
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    media_type = "audio/wav" if request.response_format == "wav" else "audio/mpeg"
    headers = {"X-TTS-Engine": result.engine}
    if result.fallback_reason:
        headers["X-TTS-Fallback"] = result.fallback_reason.encode("ascii", "replace").decode()
    return FileResponse(
        result.path,
        media_type=media_type,
        filename=f"speech.{request.response_format}",
        headers=headers,
        background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
