"""Fork-specific vision capability judgments (isolated from upstream ``capabilities``).

Everything in this module is *ours*. It keeps all DeepTutor-fork additions for
vision-capability detection in one place so the shared upstream module
``deeptutor.services.llm.capabilities`` stays close to upstream and easy to
rebase. ``capabilities.py`` pulls the judges in through a small end-of-file
hook (see its ``_make_vision_judges`` call) and merges :data:`FORK_MODEL_OVERRIDES`
into its ``MODEL_OVERRIDES`` dict.

Design notes (keep this file import-safe and dependency-light):
- No module-top ``deeptutor`` imports. The judges are *parameterised* on the
  merged override dict, so ``capabilities.py`` passes the fused
  ``MODEL_OVERRIDES`` in at hook time. That avoids a circular import and keeps
  this module self-contained (stdlib + typing only).
- The two strictness levels live here together:
  * ``model_name_implies_vision`` — fail-closed, name-only. Used when *choosing*
    a model on the user's behalf (auto-discovery), where guessing wrong would
    silently hand an image to a text-only model.
  * ``model_vision_confirmed`` — strict, record-level. An explicit
    ``capabilities`` list is authoritative both ways; otherwise the model name
    must positively imply vision.
- The looser :func:`supports_vision` (provider-level optimism, used for the
  model the user *selected*) stays upstream in ``capabilities.py`` and is never
  touched by this overlay.
"""

from __future__ import annotations

from typing import Any

# Substring markers that make a model name unambiguously multimodal. Used only
# by the fail-closed ``model_name_implies_vision`` check so that brand-new VLM
# releases are recognised without a table edit. Keep these specific enough that
# a text-only model name can never match.
_VISION_NAME_MARKERS: tuple[str, ...] = (
    "-vl",
    "vl-instruct",
    "-vision",
    "vision-",
    "-omni",
    "omni-",
    "multimodal",
    "llava",
    "internvl",
    "pixtral",
    "moondream",
    "minicpm-v",
    "-ocr",
    "ocr-",
)

# Fork-added ``MODEL_OVERRIDES`` rows. ``capabilities.py``'s end-of-file hook
# merges these into the upstream ``MODEL_OVERRIDES`` dict. Longest-prefix wins
# in the judge, so the negative overrides below veto the optimistic ``gpt-4o``
# vision row for its audio / transcription / realtime siblings.
FORK_MODEL_OVERRIDES: dict[str, dict[str, object]] = {
    # Additional vision families. These matter for the capability fallback
    # router (llm/capability_fallback.py): auto-discovery is fail-closed and
    # only picks models whose vision support is *positively known*, so a model
    # missing from this table can never be auto-selected as a vision fallback.
    "gpt-4.1": {"supports_vision": True},
    "glm-4v": {"supports_vision": True},
    "glm-4.1v": {"supports_vision": True},
    "glm-4.5v": {"supports_vision": True},
    "glm-5v": {"supports_vision": True},
    "internvl": {"supports_vision": True},
    "step-1v": {"supports_vision": True},
    "step-1o": {"supports_vision": True},
    "pixtral": {"supports_vision": True},
    "yi-vl": {"supports_vision": True},
    "llama-3.2-11b-vision": {"supports_vision": True},
    "llama-3.2-90b-vision": {"supports_vision": True},
    "paddleocr-vl": {"supports_vision": True},
    "ovis": {"supports_vision": True},
    "got-ocr": {"supports_vision": True},
    "doubao-vision": {"supports_vision": True},
    "doubao-1.5-vision": {"supports_vision": True},
    "hunyuan-vision": {"supports_vision": True},
    "ernie-4.5-vl": {"supports_vision": True},
    # ...but the gpt-4o *audio* siblings are speech endpoints that share the
    # prefix. Longest-prefix wins in the judge, so these veto the gpt-4o row
    # and keep them out of any vision routing decision.
    "gpt-4o-mini-tts": {"supports_vision": False},
    "gpt-4o-transcribe": {"supports_vision": False},
    "gpt-4o-mini-transcribe": {"supports_vision": False},
    "gpt-4o-audio": {"supports_vision": False},
    "gpt-4o-mini-audio": {"supports_vision": False},
    "gpt-4o-realtime": {"supports_vision": False},
    "gpt-4o-mini-realtime": {"supports_vision": False},
}


def _make_vision_judges(
    overrides: dict[str, dict[str, object]],
) -> tuple[Any, Any]:
    """Build ``(model_name_implies_vision, model_vision_confirmed)`` bound to *overrides*.

    *overrides* is the fully merged override table (upstream ``MODEL_OVERRIDES``
    updated with :data:`FORK_MODEL_OVERRIDES`), passed in by ``capabilities.py``
    so this module stays free of any ``deeptutor`` import at module top.
    """
    _overrides = overrides or {}

    def _override_vision(model: str | None) -> bool | None:
        """``supports_vision`` as *explicitly stated* by the merged overrides.

        Returns ``None`` when no override pattern states it — unlike the loose
        ``supports_vision`` this never falls back to the provider level, where
        the generic ``openai`` binding optimistically claims vision for every
        OpenAI-compatible endpoint (SiliconFlow, SenseNova, vLLM, ...).
        """
        if not model:
            return None
        model_lower = model.lower()
        for pattern, ov in sorted(_overrides.items(), key=lambda x: -len(x[0])):
            if model_lower.startswith(pattern) and "supports_vision" in ov:
                return bool(ov["supports_vision"])
        return None

    def model_name_implies_vision(model: str | None) -> bool:
        """Fail-closed, name-only vision check.

        ``True`` only when the model name itself is recognisably multimodal: an
        explicit override hit, or a naming marker such as ``-vl`` / ``-vision``
        / ``llava``. Provider-level optimism is deliberately excluded, so an
        unknown model on an OpenAI-compatible endpoint answers ``False``.
        """
        stated = _override_vision(model)
        if stated is not None:
            return stated
        name = (model or "").lower()
        return any(marker in name for marker in _VISION_NAME_MARKERS)

    def model_vision_confirmed(
        model_record: dict[str, Any] | None,
        binding: str | None = None,
    ) -> bool:
        """Strict vision check for a catalog model record.

        Resolution order:

        1. an explicit ``capabilities`` list is authoritative (both ways);
        2. otherwise the model *name* must positively imply vision
           (:func:`model_name_implies_vision`).

        This is what the capability fallback router uses when *choosing* a model
        on the user's behalf: guessing wrong would silently send images to a
        text-only model on an unrelated profile, which is worse than degrading.
        The looser ``supports_vision`` remains correct for judging the model the
        user explicitly selected, where an optimistic attempt plus the existing
        degrade retry is the desired behaviour.
        """
        record = model_record or {}
        caps = record.get("capabilities")
        if isinstance(caps, list) and caps:
            return "image" in caps
        return model_name_implies_vision(record.get("model"))

    return model_name_implies_vision, model_vision_confirmed


__all__ = [
    "FORK_MODEL_OVERRIDES",
    "_make_vision_judges",
]
