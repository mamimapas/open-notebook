"""
kokoro_adapter.py — Adaptador TTS OpenAI-compatible -> Kokoro-82M (voces neuronales locales, gratis).
Inputs: POST /v1/audio/speech  {"model":..., "input":"texto", "voice":"alvaro|elvira|es-ES-AlvaroNeural|...", "response_format":"mp3", "speed":1.0}
Outputs: audio binario (audio/mpeg por defecto; wav si se pide).
Cuándo usarlo: alternativa a edge_tts_adapter para podcasts open-notebook. Kokoro suena mucho más
  natural que Edge ("menos Loquendo") y es ligero (82M params, corre en CPU casi en tiempo real),
  muy por debajo del coste de VibeVoice. Mismo contrato OpenAI-compatible → cambio limpio.
Coste: 0 (modelo local Apache-2.0, sin API key).
Agente responsable: (infra open-notebook — ninguno de research)
"""
import logging
import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("TTS_PORT", "7999"))
# Override global de velocidad (open-notebook siempre manda 1.0). 1.2 = +20%. Kokoro lo aplica nativo.
TTS_SPEED_OVERRIDE = os.environ.get("TTS_SPEED")
SAMPLE_RATE = 24000  # Kokoro genera a 24 kHz

# Mapeo voice_id (alias OpenAI o nombres Edge heredados) -> (lang_code Kokoro, voz Kokoro).
# lang_code: 'e' = español, 'a' = inglés US, 'b' = inglés UK.
# Voces ES: em_alex / em_santa (masc), ef_dora (fem). Voces EN: am_michael/am_adam, af_heart/af_bella.
MALE_ES = ("e", "em_alex")
FEMALE_ES = ("e", "ef_dora")
MALE_EN = ("a", "am_michael")
FEMALE_EN = ("a", "af_heart")
VOICE_MAP = {
    # masculinas ES
    "alvaro": MALE_ES, "male": MALE_ES, "man": MALE_ES, "hombre": MALE_ES,
    "echo": MALE_ES, "onyx": MALE_ES, "ash": MALE_ES, "alloy": MALE_ES, "fable": MALE_ES,
    "es-es-alvaroneural": MALE_ES,
    # femeninas ES
    "elvira": FEMALE_ES, "female": FEMALE_ES, "woman": FEMALE_ES, "mujer": FEMALE_ES,
    "shimmer": FEMALE_ES, "nova": FEMALE_ES, "coral": FEMALE_ES, "sage": FEMALE_ES,
    "es-es-elviraneural": FEMALE_ES, "es-es-ximenaneural": FEMALE_ES,
    # inglesas
    "guy": MALE_EN, "male_en": MALE_EN, "man_en": MALE_EN, "en-us-guyneural": MALE_EN,
    "aria": FEMALE_EN, "female_en": FEMALE_EN, "woman_en": FEMALE_EN, "en-us-arianeural": FEMALE_EN,
}


def resolve_voice(voice: str):
    if not voice:
        return FEMALE_ES
    return VOICE_MAP.get(voice.strip().lower(), FEMALE_ES)


app = FastAPI(title="Kokoro TTS Adapter (OpenAI-compatible)")

# Pipelines Kokoro cacheados por lang_code (carga perezosa; el primer uso descarga el modelo).
_PIPELINES = {}


def _get_pipeline(lang_code: str):
    if lang_code not in _PIPELINES:
        from kokoro import KPipeline  # import perezoso para no pagar el coste si no se usa
        logger.info("[kokoro] inicializando pipeline lang=%s", lang_code)
        _PIPELINES[lang_code] = KPipeline(lang_code=lang_code)
    return _PIPELINES[lang_code]


class SpeechRequest(BaseModel):
    input: str
    model: str = "kokoro"
    voice: str = "elvira"
    response_format: str = "mp3"
    speed: float = 1.0


@app.get("/health")
def health():
    return {"status": "healthy", "engine": "kokoro-82m", "voices": {"male": MALE_ES[1], "female": FEMALE_ES[1]}}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "kokoro", "object": "model", "owned_by": "kokoro"}]}


def _synth_wav(text: str, lang_code: str, voice: str, speed: float, out_path: str):
    pipeline = _get_pipeline(lang_code)
    chunks = []
    for _, _, audio in pipeline(text, voice=voice, speed=speed):
        chunks.append(audio)
    if not chunks:
        raise RuntimeError("Kokoro no generó audio")
    full = np.concatenate(chunks)
    sf.write(out_path, full, SAMPLE_RATE)


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    if not req.input or not req.input.strip():
        return JSONResponse({"error": "empty input"}, status_code=400)
    lang_code, voice = resolve_voice(req.voice)
    speed = float(TTS_SPEED_OVERRIDE) if TTS_SPEED_OVERRIDE else req.speed
    fmt = (req.response_format or "mp3").lower()
    wav_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    wav_tmp.close()
    try:
        _synth_wav(req.input, lang_code, voice, speed, wav_tmp.name)
        if fmt in ("wav", "pcm"):
            logger.info("[kokoro] voice=%s lang=%s chars=%d -> wav", voice, lang_code, len(req.input))
            return FileResponse(wav_tmp.name, media_type="audio/wav", filename="speech.wav")
        # mp3: convertir con ffmpeg (sin re-muestrear de más; 128k estéreo-mono natural)
        mp3_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        mp3_tmp.close()
        subprocess.run(["ffmpeg", "-y", "-i", wav_tmp.name, "-codec:a", "libmp3lame",
                        "-b:a", "128k", mp3_tmp.name], check=True, capture_output=True)
        logger.info("[kokoro] voice=%s lang=%s chars=%d -> mp3", voice, lang_code, len(req.input))
        return FileResponse(mp3_tmp.name, media_type="audio/mpeg", filename="speech.mp3")
    except Exception as e:
        logger.exception("Error sintetizando con Kokoro")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        try:
            os.unlink(wav_tmp.name)
        except OSError:
            pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
