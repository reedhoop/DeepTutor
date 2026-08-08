"""FastAPI router exposing educational LLM presets (ER-3).

Mounted onto ``deeptutor.api.routers.settings.router`` at API-startup import
time by ``apply_educational_llm_presets_overlay()`` (see ``_local/__init__.py``),
so it inherits the ``/api/v1/settings`` prefix and the ``_auth`` dependency
already applied to that router. No upstream file is edited.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deeptutor._local.llm_presets import (
    build_profile_from_preset,
    get_educational_llm_presets,
)
from deeptutor.api.routers.settings import _require_settings_admin
from deeptutor.services.config.model_catalog import get_model_catalog_service

router = APIRouter()


class ApplyPresetPayload(BaseModel):
    preset_id: str


@router.get("/llm-presets")
async def list_llm_presets() -> dict[str, Any]:
    """Educational LLM presets available for one-click selection in the UI."""
    return {"presets": get_educational_llm_presets()}


@router.post("/llm-presets/apply", dependencies=[Depends(_require_settings_admin)])
async def apply_llm_preset(payload: ApplyPresetPayload) -> dict[str, Any]:
    """Append a preset as a new LLM profile and return the updated catalog.

    The new profile becomes the active LLM profile so the one-click action is
    immediately usable; existing profiles and the rest of the catalog are left
    untouched. The caller (settings UI) re-fetches ``GET /api/v1/settings``
    afterwards to refresh its view.
    """
    profile = build_profile_from_preset(payload.preset_id)
    if profile is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown preset: {payload.preset_id}"
        )

    service = get_model_catalog_service()

    def _mutate(catalog: dict[str, Any]) -> None:
        llm = catalog["services"]["llm"]
        llm["profiles"].append(profile)
        llm["active_profile_id"] = profile["id"]
        if profile["models"]:
            llm["active_model_id"] = profile["models"][0]["id"]

    catalog = service.update(_mutate)
    return {"catalog": catalog}
