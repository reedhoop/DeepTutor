"""Voice endpoints — text-to-speech and speech-to-text.

These are thin HTTP surfaces over :mod:`deeptutor.services.voice`. Config comes
from the admin-managed model catalog (``services.tts`` / ``services.stt``), so
voice is shared infrastructure like embedding/search — any authenticated user
may call it; it is not gated by per-user LLM grants.
"""

from __future__ import annotations

import io
import logging
import wave

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from deeptutor.services.config.model_catalog import get_model_catalog_service
from deeptutor.services.voice import (
    VoiceProviderError,
    synthesize_speech,
    transcribe_audio,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Guard against pathological uploads (the providers cap well below this anyway).
_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB, matching OpenAI's limit.
_DEFAULT_PCM_SAMPLE_RATE = 24_000
_DEFAULT_PCM_CHANNELS = 1
_PCM16_SAMPLE_WIDTH = 2


class TTSRequest(BaseModel):
    """Text-to-speech request body."""

    text: str = Field(..., min_length=1)
    voice: str | None = None
    format: str | None = None


def _parse_pcm_content_type(content_type: str) -> tuple[int, int] | None:
    """Return ``(sample_rate, channels)`` when a provider sent raw PCM audio."""
    media_type, *params = (content_type or "").split(";")
    if media_type.strip().lower() not in {"audio/pcm", "audio/x-pcm", "audio/l16"}:
        return None
    sample_rate = _DEFAULT_PCM_SAMPLE_RATE
    channels = _DEFAULT_PCM_CHANNELS
    for item in params:
        key, sep, value = item.strip().partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip().strip('"')
        try:
            parsed = int(value)
        except ValueError:
            continue
        if key in {"rate", "sample-rate", "samplerate"} and parsed > 0:
            sample_rate = parsed
        elif key in {"channels", "channel"} and parsed > 0:
            channels = parsed
    return sample_rate, channels


def _pcm16_to_wav(audio: bytes, *, sample_rate: int, channels: int) -> bytes:
    """Wrap provider PCM16 bytes in a WAV container browsers can play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(_PCM16_SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
    return buffer.getvalue()


@router.get("/voices")
async def list_tts_voices() -> dict[str, Any]:
    """List the TTS voices available from the configured model catalog.

    For every configured TTS model we surface its own voice plus, when the
    provider publishes preset voices for that model (e.g. CosyVoice2's eight
    timbres), those presets too — so the UI can offer a voice picker without
    the admin duplicating models in the catalog. Secrets (base_url / api_key)
    are never returned.
    """
    from deeptutor.services.config.provider_runtime import (  # local import: heavy + avoids any import cycle
        TTS_PROVIDERS,
        _canonical_voice_provider,
    )

    catalog = get_model_catalog_service().load()
    tts_block = (catalog.get("services") or {}).get("tts") or {}
    profiles = tts_block.get("profiles") or []

    voices: list[dict[str, str]] = []
    seen: set[str] = set()

    for profile in profiles:
        profile_id = profile.get("id") or ""
        profile_name = profile.get("name") or ""
        provider = _canonical_voice_provider(profile.get("binding"), TTS_PROVIDERS)
        spec = TTS_PROVIDERS.get(provider)
        for model in profile.get("models") or []:
            model_id = model.get("model") or ""
            configured_voice = (model.get("voice") or "").strip()
            label = (model.get("voice_label") or "").strip() or (
                next(
                    (
                        p.get("label") or ""
                        for p in (spec.preset_models if spec else ())
                        if p.get("voice") == configured_voice
                    ),
                    "",
                )
            )
            if configured_voice:
                key = f"{profile_id}::{configured_voice}"
                if key not in seen:
                    seen.add(key)
                    voices.append(
                        {
                            "id": key,
                            "voice": configured_voice,
                            "label": label or configured_voice,
                            "model": model_id,
                            "provider": provider,
                            "profile_id": profile_id,
                            "profile_name": profile_name,
                        }
                    )
            # Expand provider presets that target this model id (e.g. all
            # CosyVoice2 timbres sharing one model endpoint).
            if spec:
                for preset in spec.preset_models:
                    if preset.get("model") != model_id:
                        continue
                    preset_voice = (preset.get("voice") or "").strip()
                    if not preset_voice:
                        continue
                    key = f"{profile_id}::{preset_voice}"
                    if key in seen:
                        continue
                    seen.add(key)
                    voices.append(
                        {
                            "id": key,
                            "voice": preset_voice,
                            "label": preset.get("label") or preset_voice,
                            "model": model_id,
                            "provider": provider,
                            "profile_id": profile_id,
                            "profile_name": profile_name,
                        }
                    )
    return {"voices": voices}


@router.post("/tts")
async def text_to_speech(payload: TTSRequest) -> Response:
    """Synthesize ``text`` to audio using the active TTS provider."""
    try:
        audio, content_type = await synthesize_speech(
            payload.text,
            voice=payload.voice,
            response_format=payload.format,
        )
    except ValueError as exc:  # missing/invalid configuration
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoiceProviderError as exc:
        logger.warning("TTS provider error: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    pcm_info = _parse_pcm_content_type(content_type)
    if pcm_info:
        sample_rate, channels = pcm_info
        audio = _pcm16_to_wav(audio, sample_rate=sample_rate, channels=channels)
        content_type = "audio/wav"
    return Response(
        content=audio,
        media_type=content_type,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/stt")
async def speech_to_text(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> dict[str, str]:
    """Transcribe an uploaded audio clip using the active STT provider."""
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio upload.")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio exceeds the 25 MB limit.",
        )
    try:
        text = await transcribe_audio(
            audio,
            filename=file.filename or "audio.webm",
            content_type=file.content_type or "application/octet-stream",
            language=language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VoiceProviderError as exc:
        logger.warning("STT provider error: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"text": text}
