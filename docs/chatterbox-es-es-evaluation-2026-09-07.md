# Chatterbox es-ES canary evaluation

Status: `KEEP_CURRENT` (verified 2026-09-07).

The official `ResembleAI/Chatterbox-Multilingual-es-es` Space was pinned at
commit `f7991c03de6130583b1f103477d139de96329994` and integrated behind an
OpenAI-compatible local sidecar. It supports the reviewed female and male
Spain-Spanish references, lossless chunking, serialized CPU inference, bounded
input, observable fallback, container-signature validation and Edge TTS
continuity. Model data is mounted from `G:\FASTAPI\models\chatterbox-es-es`.

## Verification

- Unit and contract tests: 16 passed.
- Ruff: passed.
- Docker Compose validation and image build: passed.
- Female cold run: 102.477 s wall for 4.056 s audio, Chatterbox engine.
- Male warm run: 38.901 s wall for 4.896 s audio, Chatterbox engine.
- Edge male baseline: 0.708 s wall for 4.272 s audio.
- Warm wall-time ratio: 54.945x; Chatterbox real-time factor: 7.945.
- Induced missing-source failure: HTTP 200 with 20,880 bytes from `edge-tts`.
- `pip-audit`: failed with 44 known findings in four packages, including the
  official direct pins `diffusers==0.29.0` and `transformers==4.46.3`.

## Operational decision

Do not register or promote the candidate in the production `sapiens_dueto`
profile. `docker-compose.chatterbox.yml` places it behind the explicit
`chatterbox-canary` profile, disables automatic restart and leaves port 7999
stopped. OpenNote and Edge remain healthy on ports 5055 and 7998. The code,
image and 3.21 GB model cache are retained for a future compatible, secure and
fast runtime; production must not switch until the benchmark and dependency
security gates pass.
