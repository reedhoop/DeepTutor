"""vLLM-backend for OvisOCR2: PDF → images → OpenAI-compatible chat → Markdown.

This module contains the real parsing logic — rendering PDF pages into
images and calling the self-hosted vLLM server for end-to-end VLM
document parsing.  ``canvas_size`` and Leptonica-style pre-processing
are deliberately omitted (VLM natively handles multi-scale resolution),
keeping the pipeline simple.

Serving (the official model card only documents offline vLLM usage; an
OpenAI-compatible server works with stock vLLM >= 0.22.1 — OvisOCR2 uses
the standard ``Qwen3_5ForConditionalGeneration`` architecture)::

    vllm serve ATH-MaaS/OvisOCR2 --port 8200

which serves ``ATH-MaaS/OvisOCR2`` at ``http://127.0.0.1:8200/v1``.
(We default to :8200 rather than vLLM's stock :8000, which is far too
commonly taken by other local dev servers.)

Alignment with the official model card (https://modelscope.cn/models/ATH-MaaS/OvisOCR2):
- ``_DEFAULT_OCR_PROMPT`` is the card's fixed instruction prompt, verbatim
  (including the leading newline).  The card warns outputs are tuned to
  this exact wording — do not "improve" it.
- ``enable_thinking=False`` is card-mandated (Qwen3.5 chat templates may
  otherwise inject a thinking preamble); passed via ``chat_template_kwargs``.
- Official sampling: ``max_tokens=16384, temperature=0.0``.
- Post-processing mirrors the card's parser: strip → filter
  ``<img src="images/bbox_..." />`` visual-region tags (we do not crop
  region images, so the links would dangle) → trim truncated repeats.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Callable, Optional

import httpx

from .config import OvisOCR2Config, OvisOCR2Error

logger = logging.getLogger(__name__)

# Bounded retry for transient vLLM failures: a self-hosted endpoint under load
# routinely returns 429/5xx or drops a connection, and one hiccup must not abort
# a whole multi-page parse. Exponential backoff 1s, 2s, 4s.
_VLLM_MAX_ATTEMPTS = 3
_VLLM_RETRY_BASE_DELAY = 1.0

# -- default prompt used for OvisOCR2 VLM OCR --------------------------------
# Verbatim from the official model card (including the leading newline).
# The card warns outputs are tuned to this exact wording — don't rephrase.

_DEFAULT_OCR_PROMPT = (
    "\nExtract all readable content from the image in natural human reading order "
    "and output the result as a single Markdown document. For charts or images, "
    'represent them using an HTML image tag: '
    '<img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, '
    "where left, top, right, bottom are bounding box coordinates scaled to [0, 1000). "
    "Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all other text as standard Markdown. "
    "Preserve the original text without translation or paraphrasing."
)


# -- official post-processing (mirrors the model card's parser) ---------------

def _filter_bbox_imgtags(text: str) -> str:
    """Drop ``<img src="images/bbox_..." />`` visual-region blocks.

    The official parser filters these by default (``filter_imgtags=True``);
    we do the same because we don't crop region images, so the referenced
    files would not exist."""
    return "\n\n".join(
        block
        for block in text.split("\n\n")
        if not block.strip().startswith('<img src="images/bbox_')
    )


def _clean_truncated_repeats(
    text: str,
    min_text_len: int = 8000,
    max_period: int = 200,
    min_period: int = 1,
    min_repeat_chars: int = 100,
    min_repeat_times: int = 5,
) -> str:
    """Trim degenerate repeated tails from long outputs (official algorithm,
    copied verbatim from the model card)."""
    n = len(text)
    if n < min_text_len:
        return text

    max_period = min(max_period, n - 1)
    for unit_len in range(min_period, max_period + 1):
        if text[n - 1] != text[n - 1 - unit_len]:
            continue

        match_len = 1
        idx = n - 2
        while idx >= unit_len and text[idx] == text[idx - unit_len]:
            match_len += 1
            idx -= 1

        total_len = match_len + unit_len
        repeat_times = total_len // unit_len
        tail_len = total_len % unit_len

        if repeat_times >= min_repeat_times and total_len >= min_repeat_chars:
            return text[: n - total_len + unit_len] + text[n - tail_len:]

    return text


def _postprocess_page_markdown(text: str) -> str:
    """Official page post-processing: strip → filter img tags → trim repeats."""
    return _clean_truncated_repeats(_filter_bbox_imgtags(text.strip()))


# -- probe ------------------------------------------------------------------

def probe_vllm(config: OvisOCR2Config) -> tuple[bool, str]:
    """Check whether the configured vLLM endpoint is reachable and serves
    the requested model.  Returns ``(ok, message)``."""
    try:
        headers = {"Authorization": f"Bearer {config.api_token}"} if config.api_token else {}
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{config.api_base_url}/models", headers=headers)
        if r.status_code != 200:
            return False, f"vLLM returned HTTP {r.status_code}: {r.text[:200]}"
        models = [m["id"] for m in r.json().get("data", [])]
        if config.model_name not in models:
            return False, (
                f"Model '{config.model_name}' not found at vLLM endpoint. "
                f"Available: {', '.join(models[:10])}"
                + ("..." if len(models) > 10 else "")
            )
        return True, "Ready to parse."
    except httpx.ConnectError:
        return False, f"Could not connect to {config.api_base_url}"
    except Exception as exc:  # noqa: BLE001 — best-effort probe
        return False, f"vLLM unreachable: {exc}"


# -- PDF rendering ----------------------------------------------------------

def render_pdf_pages(source_path: Path, output_dir: Path, *, dpi: int = 200) -> list[Path]:
    """Render every page of ``source_path`` as ``<page>.png`` into ``output_dir``.
    Returns the list of image paths in page order."""
    import fitz  # PyMuPDF — already a project dependency

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    try:
        doc = fitz.open(str(source_path))
    except Exception as exc:
        raise OvisOCR2Error(f"Cannot open PDF with PyMuPDF: {exc}") from exc

    try:
        for i in range(len(doc)):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi)
            png_path = output_dir / f"page_{i + 1:04d}.png"
            pix.save(str(png_path))
            paths.append(png_path)
    finally:
        doc.close()
    return paths


# -- vLLM chat call (single page) -------------------------------------------

async def _call_vllm_page(
    client: httpx.AsyncClient,
    png_path: Path,
    config: OvisOCR2Config,
    sem: asyncio.Semaphore,
    *,
    prompt: str = _DEFAULT_OCR_PROMPT,
) -> str:
    """Send one page image to the vLLM endpoint, return the model's Markdown."""
    b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
    headers = {"Authorization": f"Bearer {config.api_token}"} if config.api_token else {}
    body = {
        "model": config.model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        # Card-mandated: Qwen3.5 chat templates may inject a thinking
        # preamble unless explicitly disabled.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    async with sem:
        last_status: int | None = None
        for attempt in range(_VLLM_MAX_ATTEMPTS):
            try:
                response = await client.post(
                    f"{config.api_base_url}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=httpx.Timeout(config.timeout_s, connect=30.0),
                )
            except (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
                httpx.PoolTimeout,
            ) as exc:
                if attempt + 1 >= _VLLM_MAX_ATTEMPTS:
                    raise OvisOCR2Error(
                        f"vLLM unreachable after {_VLLM_MAX_ATTEMPTS} attempts: {exc}"
                    ) from exc
                await asyncio.sleep(_VLLM_RETRY_BASE_DELAY * (2 ** attempt))
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                last_status = response.status_code
                if attempt + 1 >= _VLLM_MAX_ATTEMPTS:
                    break
                await asyncio.sleep(_VLLM_RETRY_BASE_DELAY * (2 ** attempt))
                continue
            if response.status_code != 200:
                snippet = response.text[:300]
                raise OvisOCR2Error(
                    f"vLLM returned HTTP {response.status_code} for page "
                    f"{png_path.name}: {snippet}"
                )
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                raise OvisOCR2Error(f"vLLM returned no choices for page {png_path.name}")
            return choices[0].get("message", {}).get("content", "") or ""
        raise OvisOCR2Error(
            f"vLLM returned HTTP {last_status} for page {png_path.name} "
            f"after {_VLLM_MAX_ATTEMPTS} attempts"
        )


# -- top-level parse entry point ---------------------------------------------

async def _parse_pages_async(
    pages: list[Path],
    config: OvisOCR2Config,
    on_output: Optional[Callable[[str], None]],
    *,
    prompt: str = _DEFAULT_OCR_PROMPT,
) -> list[str]:
    """Concurrent page processing with rate limiting."""
    sem = asyncio.Semaphore(config.max_concurrency)
    headers = {"Authorization": f"Bearer {config.api_token}"} if config.api_token else {}

    results: list[str] = []
    total = len(pages)
    async with httpx.AsyncClient(headers=headers) as client:
        for idx, png_path in enumerate(pages, 1):
            if on_output:
                on_output(f"OvisOCR2 parsing page {idx}/{total}...")
            try:
                md = await _call_vllm_page(client, png_path, config, sem, prompt=prompt)
            except OvisOCR2Error:
                raise
            except Exception as exc:
                raise OvisOCR2Error(
                    f"vLLM call failed for page {idx}/{total}: {exc}"
                ) from exc
            results.append(_postprocess_page_markdown(md))
    return results


def _build_prompt(config: OvisOCR2Config) -> str:
    prompt = _DEFAULT_OCR_PROMPT
    if config.language and config.language.lower() != "auto":
        prompt += f"\n\nPreferred output language: {config.language}."
    if config.extra_prompt:
        prompt += f"\n\n{config.extra_prompt}"
    return prompt


def parse_pdf_via_vllm(
    source_path: Path,
    workdir: Path,
    *,
    config: OvisOCR2Config,
    on_output: Optional[Callable[[str], None]] = None,
) -> None:
    """Main entry point: render PDF → call vLLM per page → write ``<stem>.md``.

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

    prompt = _build_prompt(config)

    results = _run_async(
        _parse_pages_async(pages, config, on_output, prompt=prompt)
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


__all__ = ["parse_pdf_via_vllm", "probe_vllm", "render_pdf_pages"]
