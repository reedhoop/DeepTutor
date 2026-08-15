"""PaddleOCR-VL parsing backend: PDF → images → vLLM, aligned with the
official PaddleOCR-VL guidance.

Two modes, selected by ``PaddleOCR_VLConfig.enable_layout``:

* **Layout-assisted (recommended, default):** run PP-DocLayoutV2 locally to
  detect per-page regions (text / table / formula / chart / seal / …), crop
  each region, and call the PaddleOCR-VL vLLM endpoint with the matching task
  prompt (``OCR:`` / ``Table Recognition:`` / ``Formula Recognition:`` /
  ``Chart Recognition:``), reassembling the page in reading order.  PP-DocLayoutV2
  is ~204 MB and downloads on first use (Paddle Inference, no GPU required).
* **Whole-page (fallback):** send the full rendered page with the official
  document-parsing prompt.  Used when layout is disabled or PP-DocLayoutV2 is
  unavailable, so the engine still parses without ``paddleocr`` installed.

PP-DocLayoutV2 is import-guarded: when ``paddleocr`` isn't installed we silently
fall back to whole-page mode rather than failing the parse.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from ..ovisocr2.backend import _call_vllm_page, render_pdf_pages
from .config import PaddleOCR_VLConfig

logger = logging.getLogger(__name__)

# Official whole-page document-parsing prompt (PaddleOCR-VL via vLLM).
_PAGE_PROMPT = (
    "Convert the document image into clean, well-structured Markdown. "
    "Recognize all text, tables, formulas, and charts.\n"
    "Rules:\n"
    "- Preserve the natural reading order.\n"
    "- Tables → Markdown table syntax.\n"
    "- Formulas → LaTeX ($...$ for inline, $$...$$ for display).\n"
    "- Charts → describe the key data series and axes in Markdown.\n"
    "- Output ONLY the Markdown, no explanations, no code fences.\n"
    "- Use the document's original language."
)

# Region task prompts, per the official PaddleOCR-VL tasks.
_TASK_OCR = "OCR:"
_TASK_TABLE = "Table Recognition:"
_TASK_FORMULA = "Formula Recognition:"
_TASK_CHART = "Chart Recognition:"


def _task_prompt_for_label(label: str) -> str:
    """Map a PP-DocLayoutV2 region label to its PaddleOCR-VL task prompt."""
    key = (label or "").lower()
    if "table" in key:
        return _TASK_TABLE
    if "formula" in key or "equation" in key:
        return _TASK_FORMULA
    if "chart" in key:
        return _TASK_CHART
    # text / title / paragraph / seal / figure caption / image / … → OCR.
    return _TASK_OCR


def _paddle_layout_available() -> bool:
    """Whether the local PP-DocLayoutV2 dependency (``paddleocr``) is importable."""
    try:
        return importlib.util.find_spec("paddleocr") is not None
    except Exception:
        return False


def _normalize_bbox(coord) -> Optional[tuple[float, float, float, float]]:
    """Normalize a bbox into ``(x1, y1, x2, y2)`` pixel coords.

    Accepts ``[x1, y1, x2, y2]``, an 8-value flat polygon, or a list of
    ``[x, y]`` points. Returns ``None`` if it cannot be parsed."""
    try:
        pts = list(coord)
    except Exception:
        return None
    if not pts:
        return None
    try:
        if all(isinstance(p, (list, tuple)) for p in pts):
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
        else:
            nums = [float(v) for v in pts]
            if len(nums) == 4:
                xs = [nums[0], nums[2]]
                ys = [nums[1], nums[3]]
            elif len(nums) == 8:
                xs = nums[0::2]
                ys = nums[1::2]
            else:
                return None
    except (TypeError, ValueError):
        return None
    return (min(xs), min(ys), max(xs), max(ys))


_LAYOUT_MODEL: Any = None


def _get_layout_model() -> Any:
    """Return the shared PP-DocLayoutV2 instance (loaded once per process).

    The model is ~204 MB and loads from disk/network on first use; constructing
    it per page made multi-page parses unusably slow and OOM-prone. A single
    process-wide instance is reused across pages. ``predict`` is stateless, so
    sharing is safe under the current serial page loop.
    """
    global _LAYOUT_MODEL
    if _LAYOUT_MODEL is None:
        from paddleocr import LayoutDetection

        _LAYOUT_MODEL = LayoutDetection(model_name="PP-DocLayoutV2")
    return _LAYOUT_MODEL


def _detect_layout(page_path: Path) -> Optional[list[dict]]:
    """Detect layout regions for one rendered page.

    Returns a reading-order-sorted list of
    ``{"label", "bbox": (x1, y1, x2, y2), "order"}`` dicts, or ``None`` when
    detection is unavailable or fails (caller falls back to whole-page).
    """
    try:
        model = _get_layout_model()
    except Exception:
        return None
    try:
        outputs = model.predict(str(page_path), batch_size=1, layout_nms=True)
        regions: list[dict] = []
        for out in outputs:
            boxes = getattr(out, "boxes", None) or []
            order_hint = getattr(out, "layout", None)  # reading-order index list
            for idx, box in enumerate(boxes):
                label = str(
                    getattr(box, "label", "") or getattr(box, "category", "")
                ).lower()
                if not label:
                    continue
                bbox = _normalize_bbox(
                    getattr(box, "bbox", None) or getattr(box, "coordinate", None)
                )
                if bbox is None:
                    continue
                order = getattr(box, "order", None)
                if order is None and order_hint is not None:
                    try:
                        order = order_hint.index(idx)
                    except Exception:
                        order = None
                regions.append({"label": label, "bbox": bbox, "order": order})
        if not regions:
            return None
        regions.sort(
            key=lambda r: (
                r["order"] if r["order"] is not None else 1 << 30,
                r["bbox"][1],
                r["bbox"][0],
            )
        )
        return regions
    except Exception as exc:  # noqa: BLE001 - fall back to whole-page mode
        logger.warning(
            "PP-DocLayoutV2 layout detection failed (%s); whole-page fallback.", exc
        )
        return None


async def _parse_page_layout(
    client: httpx.AsyncClient,
    page_path: Path,
    regions: list[dict],
    config: PaddleOCR_VLConfig,
    sem: asyncio.Semaphore,
) -> str:
    """Crop each region and call vLLM with its task prompt; join in order."""
    from PIL import Image  # lazy: only needed in layout mode

    try:
        page_img = Image.open(page_path)
    except Exception as exc:
        logger.warning("Cannot open rendered page %s: %s", page_path, exc)
        return ""
    parts: list[str] = []
    for region in regions:
        x1, y1, x2, y2 = (int(v) for v in region["bbox"])
        crop = page_img.crop((x1, y1, x2, y2))
        if crop.width < 2 or crop.height < 2:
            continue
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        crop_path = Path(tmp.name)
        tmp.close()
        try:
            crop.save(crop_path)
            region_prompt = _task_prompt_for_label(region["label"])
            if config.extra_prompt:
                region_prompt = f"{region_prompt}\n\n{config.extra_prompt}"
            md = await _call_vllm_page(
                client,
                crop_path,
                config,
                sem,
                prompt=region_prompt,
            )
        finally:
            crop_path.unlink(missing_ok=True)
        md = (md or "").strip()
        if md:
            parts.append(md)
    return "\n\n".join(parts)


async def _parse_page_whole(
    client: httpx.AsyncClient,
    page_path: Path,
    config: PaddleOCR_VLConfig,
    sem: asyncio.Semaphore,
) -> str:
    prompt = _PAGE_PROMPT
    if config.extra_prompt:
        prompt = f"{prompt}\n\n{config.extra_prompt}"
    return await _call_vllm_page(client, page_path, config, sem, prompt=prompt)


async def _parse_pages_async(
    pages: list[Path],
    config: PaddleOCR_VLConfig,
    on_output: Optional[Callable[[str], None]],
    sem: asyncio.Semaphore,
) -> list[str]:
    headers = {"Authorization": f"Bearer {config.api_token}"} if config.api_token else {}
    results: list[str] = []
    total = len(pages)
    async with httpx.AsyncClient(headers=headers) as client:
        for idx, page_path in enumerate(pages, 1):
            if on_output:
                on_output(f"PaddleOCR-VL parsing page {idx}/{total}...")
            if config.enable_layout and _paddle_layout_available():
                regions = await asyncio.to_thread(_detect_layout, page_path)
                if regions:
                    md = await _parse_page_layout(client, page_path, regions, config, sem)
                else:
                    md = await _parse_page_whole(client, page_path, config, sem)
            else:
                md = await _parse_page_whole(client, page_path, config, sem)
            results.append(md)
    return results


def parse_pdf_via_paddleocr_vl(
    source_path: Path,
    workdir: Path,
    *,
    config: PaddleOCR_VLConfig,
    on_output: Optional[Callable[[str], None]] = None,
) -> None:
    """Main entry point: render PDF → call vLLM (layout or whole-page) →
    write ``<stem>.md``.

    Writes into ``workdir/``:
    - ``images/page_0001.png ...``  (rendered pages)
    - ``<stem>.md``                  (concatenated Markdown from all pages)
    """
    stem = Path(source_path).stem
    images_dir = Path(workdir) / "images"

    if on_output:
        on_output(f"Rendering {Path(source_path).name} at {config.image_dpi} dpi...")
    pages = render_pdf_pages(source_path, images_dir, dpi=config.image_dpi)
    if not pages:
        (Path(workdir) / f"{stem}.md").write_text("", encoding="utf-8")
        return

    mode = (
        "layout-assisted"
        if (config.enable_layout and _paddle_layout_available())
        else "whole-page"
    )
    if on_output:
        on_output(f"PaddleOCR-VL mode: {mode}")

    results = _run_async(
        _parse_pages_async(
            pages, config, on_output, asyncio.Semaphore(config.max_concurrency)
        )
    )

    out_path = Path(workdir) / f"{stem}.md"
    out_path.write_text("\n\n".join(results), encoding="utf-8")
    if on_output:
        on_output(f"Parsed {len(results)} page(s) → {out_path.name}")


def _run_async(coro):
    """Loop-safe coroutine runner (mirrors deeptutor.services.embedding.client.embed_sync).

    Falls back to a dedicated thread + event loop when invoked from inside an
    already-running asyncio loop, so it never raises
    ``RuntimeError: asyncio.run() cannot be called from a running event loop``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        return executor.submit(asyncio.run, coro).result()


__all__ = ["parse_pdf_via_paddleocr_vl"]
