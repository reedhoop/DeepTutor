"""Capability-aware LLM fallback routing (fork-local).

The chat pipeline normally uses the single user-selected ``llm`` model for
every turn — including when the user attaches an image. Some text-only models
reject image input; historically DeepTutor then silently degraded the image to
a ``[image omitted]`` placeholder (see :mod:`deeptutor.services.llm.multimodal`,
``should_degrade_to_text``).

This module upgrades that degrade into a *capability fallback router*:

* the user-selected ``llm`` model stays the priority (manual config wins);
* when the request needs a capability the primary lacks (e.g. vision) we walk
  a tiered chain instead of dropping the content:

  T1 explicit ``vlm`` slot   — a vision model the admin configured on purpose;
  T2 auto-discovery          — any other vision-capable model in the catalog;
  T3 OCR extraction          — turn the image into text via a ready OCR engine;
  T4 degrade                 — last resort, image becomes a text placeholder.

The router is capability-keyed (today only ``"image"`` is wired) so future
modalities (audio, pdf) slot in without restructuring the call sites.

Capability semantics
--------------------
Two different strictnesses are used on purpose:

* the model the **user selected** is judged with ``supports_vision`` — the
  optimistic provider-level view. If it turns out to reject the image the
  pre-existing degrade retry catches it, and we never reroute away from a
  manually chosen model on a guess;
* a model the router would **choose on the user's behalf** (T2) is judged with
  ``model_vision_confirmed`` — fail-closed. The generic ``openai`` binding
  claims vision for every OpenAI-compatible endpoint (SiliconFlow, SenseNova,
  vLLM...), so trusting it here would happily hand an image to a text-only
  DeepSeek model on an unrelated profile.

A catalog model record may carry ``capabilities: ["text", "image"]``. Absent
means "unknown, infer from the static table"; present is authoritative, in both
directions. It is intentionally never defaulted at normalization time.

Injection points
-----------------
:func:`resolve_for_turn` is consulted once per chat turn by
``AgenticChatPipeline.run`` (Stage-0 pre-flight). A ``vlm`` decision swaps the
turn's ``LLMConfig`` via ``set_scoped_llm_config``-free reassignment (the
pipeline rebuilds its client from ``self.llm_config``), and an ``ocr_text``
decision records extracted text that replaces the image parts in the user
message. The legacy retry seam in ``agent_loop.py`` remains as a safety net.
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from deeptutor.services.llm.capabilities import model_vision_confirmed, supports_vision
from deeptutor.services.llm.config import LLMConfig, get_llm_config
from deeptutor.services.config.model_catalog import get_model_catalog_service

logger = logging.getLogger(__name__)

_IMAGE_CAP = "image"

#: Services scanned by auto-discovery, most-intentional first. ``vlm`` holds a
#: model the user picked *for* vision; ``llm`` holds models they configured for
#: chat.
#:
#: Deliberately nothing else. The remaining catalog services (tts / stt /
#: imagegen / videogen / embedding) are not chat-completions endpoints, so a
#: model living there can never serve a chat turn no matter what its name
#: suggests — ``gpt-4o-mini-tts`` looks vision-capable by prefix but is a
#: speech endpoint. Widening this tuple would hand images to the wrong API.
_DISCOVERY_ORDER: tuple[str, ...] = ("vlm", "llm")


@dataclass
class FallbackDecision:
    """Outcome of :func:`resolve_for_turn`.

    ``kind`` is one of ``primary`` / ``vlm`` / ``ocr_text`` / ``degrade``.
    ``config`` carries the ``LLMConfig`` to use (always set for the first
    three; for ``degrade`` it equals the primary so callers can proceed).
    ``extracted_text`` holds OCR output for the ``ocr_text`` kind.
    """

    kind: str
    config: LLMConfig | None = None
    note: str = ""
    extracted_text: str = ""
    tiers_considered: list[str] = field(default_factory=list)


def _cost_score(model_name: str) -> int:
    """Cheaper-looking model names rank first for auto-discovery."""
    n = (model_name or "").lower()
    if any(k in n for k in ("nano", "mini", "lite", "small", "light")):
        return 0
    if any(k in n for k in ("pro", "max", "ultra", "large", "1t", "70b", "32b")):
        return 2
    return 1


def _active_profile_and_model(
    catalog: dict[str, Any] | None, service: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (profile, model) for the active model of *service*, or (None, None)."""
    if not catalog:
        return None, None
    svc = (catalog.get("services") or {}).get(service) or {}
    active_pid = svc.get("active_profile_id")
    active_mid = svc.get("active_model_id")
    for profile in svc.get("profiles") or []:
        if profile.get("id") == active_pid:
            for m in profile.get("models") or []:
                if m.get("id") == active_mid:
                    return profile, m
    # Fall back to the first profile/model so an unselected-but-present slot
    # still participates in auto-discovery.
    for profile in svc.get("profiles") or []:
        models = profile.get("models") or []
        if models:
            return profile, models[0]
    return None, None


def _build_llm_config(
    profile: dict[str, Any], model: dict[str, Any], catalog: dict[str, Any] | None
) -> LLMConfig | None:
    """Construct an :class:`LLMConfig` from a catalog (profile, model) pair.

    Delegates to :func:`deeptutor._local.capability_resolver.resolve_catalog_pair`
    so the runtime config uses the same provider matching as the Settings "Run
    test" probe (default base_url fill, local ``sk-no-key-required``, gateway
    detection) instead of a simplified hand-rolled construction that would
    mis-resolve gateway/local VLM profiles (empty base_url → OpenAI default,
    missing local key).
    """
    model_name = (model.get("model") or "").strip()
    if not model_name:
        return None
    from deeptutor._local.capability_resolver import resolve_catalog_pair

    resolved = resolve_catalog_pair(profile, model, catalog=catalog)
    return LLMConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        reasoning_effort=resolved.reasoning_effort,
    )


def _slot_model_allows_image(model: dict[str, Any] | None) -> bool:
    """Whether a model sitting in the explicit ``vlm`` slot may take images.

    Placing a model in the ``vlm`` slot *is* the declaration of intent, so the
    slot is trusted by default — the user asked for this model to handle
    images. The only veto is an explicit ``capabilities`` list that omits
    ``"image"``, i.e. the user (or the UI) said in so many words that this
    model is text-only.
    """
    caps = (model or {}).get("capabilities")
    if isinstance(caps, list) and caps:
        return _IMAGE_CAP in caps
    return True


def _discover_vision_model(
    catalog: dict[str, Any] | None, primary_model: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Scan the catalog for a *confirmed* vision model other than the primary.

    Uses the fail-closed :func:`model_vision_confirmed` check rather than
    :func:`supports_vision`: the latter inherits the ``openai`` binding's
    optimistic provider-level claim, which would let auto-discovery pick a
    text-only DeepSeek/GLM model served over an OpenAI-compatible endpoint and
    send images to it. Services are walked in :data:`_DISCOVERY_ORDER` and ties
    are broken cheapest-name-first.

    Returns (profile, model), or (None, None) when nothing is confirmed.
    """
    if not catalog:
        return None, None
    services = catalog.get("services") or {}
    primary_model = (primary_model or "").lower()
    ranking: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
    for rank, name in enumerate(_DISCOVERY_ORDER):
        svc = services.get(name) or {}
        for profile in svc.get("profiles") or []:
            binding = profile.get("binding")
            for m in profile.get("models") or []:
                if not model_vision_confirmed(m, binding):
                    continue
                if not (m.get("model") or "").strip():
                    continue
                if (m.get("model") or "").lower() == primary_model:
                    continue
                ranking.append((rank, _cost_score(m.get("model") or ""), profile, m))
    if not ranking:
        return None, None
    ranking.sort(key=lambda x: (x[0], x[1]))
    return ranking[0][2], ranking[0][3]


def _attachment_bytes(att: Any) -> bytes | None:
    """Resolve an attachment's raw bytes from base64 or a local store URL."""
    b64 = getattr(att, "base64", "") or ""
    if b64:
        try:
            return base64.b64decode(b64, validate=False)
        except Exception:
            return None
    url = getattr(att, "url", "") or ""
    if url.startswith("/api/attachments/"):
        try:
            from urllib.parse import unquote, urlparse

            from deeptutor.services.storage import get_attachment_store

            store = get_attachment_store()
            resolve = getattr(store, "resolve_path", None)
            if resolve is None:
                return None
            parsed = urlparse(url)
            parts = parsed.path[len("/api/attachments/") :].split("/")
            if len(parts) != 3:
                return None
            target = resolve(session_id=parts[0], attachment_id=parts[1], filename=unquote(parts[2]))
            if target is None:
                return None
            return target.read_bytes()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("capability fallback: local attachment resolve failed: %s", exc)
            return None
    return None


def _ocr_extract(attachments: list[Any]) -> str:
    """OCR-extract every image attachment into a single text blob.

    Returns ``""`` when no OCR engine is ready or extraction fails for all
    images, so callers fall through to plain degrade. Failures are logged but
    never raised — this is a best-effort enrichment of the user's message.
    """
    image_atts = [a for a in (attachments or []) if getattr(a, "type", "") == "image"]
    if not image_atts:
        return ""
    try:
        from deeptutor._local.engine_router import first_ready_ocr_engine
        from deeptutor.services.parsing.service import get_parse_service

        engine = first_ready_ocr_engine()
        if not engine:
            return ""
        svc = get_parse_service()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("capability fallback: OCR service unavailable: %s", exc)
        return ""

    parts: list[str] = []
    for att in image_atts:
        data = _attachment_bytes(att)
        if not data:
            continue
        tmp_path: str | None = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="dt_ocr_")
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            doc = svc.parse(tmp_path, engine=engine)
            text = (doc.markdown or "").strip()
            if text:
                parts.append(text)
        except Exception as exc:
            logger.warning("capability fallback: OCR extraction failed: %s", exc)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    return "\n\n".join(parts)


def resolve_for_turn(required_caps: set[str], attachments: list[Any] | None = None) -> FallbackDecision:
    """Resolve which model/config should serve this turn.

    ``required_caps`` is the set of capabilities the request needs (today
    ``{"image"}`` when the user attached an image). Returns a
    :class:`FallbackDecision` describing the chosen tier.
    """
    primary = get_llm_config()
    has_image = any(getattr(a, "type", "") == "image" for a in (attachments or []))
    tiers: list[str] = []

    if not has_image or _IMAGE_CAP not in required_caps:
        return FallbackDecision("primary", config=primary, tiers_considered=["primary"])

    if supports_vision(primary.binding, primary.model):
        return FallbackDecision("primary", config=primary, tiers_considered=["primary-vision"])

    # Load the catalog once for T1 + T2 (each tier used to load it again).
    try:
        catalog = get_model_catalog_service().load()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("capability fallback: catalog load failed: %s", exc)
        catalog = None

    # T1 — explicit vlm slot (user-configured vision model).
    tiers.append("vlm-slot")
    vprof, vmodel = _active_profile_and_model(catalog, "vlm")
    if vprof and vmodel and _slot_model_allows_image(vmodel):
        cfg = _build_llm_config(vprof, vmodel, catalog)
        if cfg is not None:
            return FallbackDecision("vlm", config=cfg, note="explicit vlm slot", tiers_considered=tiers)

    # T2 — auto-discover any other vision-capable model in the catalog.
    tiers.append("auto-discover")
    dprof, dmodel = _discover_vision_model(catalog, primary.model)
    if dprof and dmodel:
        cfg = _build_llm_config(dprof, dmodel, catalog)
        if cfg is not None:
            return FallbackDecision(
                "vlm", config=cfg, note="auto-discovered vision model", tiers_considered=tiers
            )

    # T3 — OCR the image(s) into text and feed the primary text model.
    tiers.append("ocr")
    text = _ocr_extract(attachments)
    if text:
        return FallbackDecision(
            "ocr_text", config=primary, extracted_text=text, note="ocr extracted text",
            tiers_considered=tiers,
        )

    # T4 — nothing available; keep the primary and let the caller degrade.
    tiers.append("degrade")
    return FallbackDecision("degrade", config=primary, note="no vision/ocr fallback", tiers_considered=tiers)


__all__ = ["FallbackDecision", "resolve_for_turn"]
