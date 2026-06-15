"""
edge_tts_adapter.py — Adaptador TTS OpenAI-compatible -> Edge TTS (voces ES peninsular, gratis).
Inputs: POST /v1/audio/speech  {"model":..., "input":"texto", "voice":"alvaro|elvira|...", "response_format":"mp3"}
Outputs: audio binario (audio/mpeg por defecto).
Cuándo usarlo: lo consume open-notebook (provider openai_compatible, modalidad text_to_speech) para sintetizar
  los podcasts. Edge TTS aguanta texto largo de forma fiable y usa voces es-ES nativas (Alvaro M / Elvira F).
Coste: 0 (servicio público de Microsoft Edge read-aloud, sin API key).
Agente responsable: (infra open-notebook — ninguno de research)
"""
import asyncio
import logging
import os
import tempfile

import edge_tts
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("TTS_PORT", "7998"))
# Velocidad global de las voces. open-notebook no expone "speed" en sus perfiles y siempre
# envía speed=1.0; este override permite acelerar (o ralentizar) todas las voces sin tocar
# open-notebook. 1.2 = +20% (voces algo más ágiles). Edge TTS lo aplica como rate "+20%".
TTS_SPEED_OVERRIDE = os.environ.get("TTS_SPEED")

# Mapeo voice_id (lo que pida open-notebook / speaker profile) -> voz Edge es-ES peninsular.
# Aceptamos tanto alias OpenAI (echo, onyx, shimmer, nova...) como nombres directos.
MALE = "es-ES-AlvaroNeural"
FEMALE = "es-ES-ElviraNeural"
FEMALE2 = "es-ES-XimenaNeural"
# Voces inglesas (US) para podcasts en inglés.
MALE_EN = "en-US-GuyNeural"
FEMALE_EN = "en-US-AriaNeural"
VOICE_MAP = {
    # masculinas ES (alias OpenAI "graves" + nombres directos)
    "alvaro": MALE, "male": MALE, "man": MALE, "hombre": MALE,
    "echo": MALE, "onyx": MALE, "ash": MALE, "alloy": MALE, "fable": MALE,
    # femeninas ES
    "elvira": FEMALE, "female": FEMALE, "woman": FEMALE, "mujer": FEMALE,
    "shimmer": FEMALE, "nova": FEMALE, "coral": FEMALE, "sage": FEMALE,
    "ximena": FEMALE2,
    # inglesas — alias dedicados para el dúo EN
    "guy": MALE_EN, "male_en": MALE_EN, "man_en": MALE_EN,
    "aria": FEMALE_EN, "female_en": FEMALE_EN, "woman_en": FEMALE_EN,
}


def resolve_voice(voice: str) -> str:
    if not voice:
        return FEMALE
    v = voice.strip()
    # nombre Edge directo (es-ES-..., en-US-..., en-GB-...)
    if "Neural" in v and (v.lower().startswith("es-") or v.lower().startswith("en-")):
        return v
    return VOICE_MAP.get(v.lower(), FEMALE)


app = FastAPI(title="Edge TTS Adapter (OpenAI-compatible)")


class SpeechRequest(BaseModel):
    input: str
    model: str = "edge-tts"
    voice: str = "elvira"
    response_format: str = "mp3"
    speed: float = 1.0


@app.get("/health")
def health():
    return {"status": "healthy", "voices": {"male": MALE, "female": FEMALE}}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "edge-tts", "object": "model", "owned_by": "edge"}]}


async def _synth(text: str, voice: str, rate: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(out_path)


@app.post("/v1/audio/speech")
async def speech(req: SpeechRequest):
    voice = resolve_voice(req.voice)
    # speed -> rate edge (1.0 -> +0%, 1.1 -> +10%, 0.9 -> -10%)
    # El override por env tiene prioridad porque open-notebook siempre manda 1.0.
    speed = float(TTS_SPEED_OVERRIDE) if TTS_SPEED_OVERRIDE else req.speed
    pct = int(round((speed - 1.0) * 100))
    rate = f"+{pct}%" if pct >= 0 else f"{pct}%"
    if not req.input or not req.input.strip():
        return JSONResponse({"error": "empty input"}, status_code=400)
    fmt = (req.response_format or "mp3").lower()
    suffix = ".mp3"
    media = "audio/mpeg"
    if fmt in ("wav", "pcm"):
        suffix, media = ".wav", "audio/wav"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:
        await _synth(req.input, voice, rate, tmp.name)
        logger.info("[edge-tts] voice=%s chars=%d -> %s", voice, len(req.input), tmp.name)
        return FileResponse(tmp.name, media_type=media, filename="speech" + suffix)
    except Exception as e:
        logger.exception("Error sintetizando")
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
