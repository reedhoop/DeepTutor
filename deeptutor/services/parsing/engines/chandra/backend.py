"""vLLM-backend for Chandra: PDF → images → OpenAI-compatible chat → Markdown.

Thin, model-agnostic adapter over a self-hosted vLLM server serving Chandra
(formula + handwriting + layout, single model). Mirrors the OvisOCR2 backend:
the same OpenAI-compatible vLLM protocol works for any end-to-end VLM OCR model,
so only the model name / endpoint (config) differ — the HTTP contract is
identical. Defaults (port :8230, empty ``model_name``) are placeholders: the
user must deploy Chandra's vLLM service and fill in the name + address under
Settings → Document Parsing before the engine can run.

Serving (example — adjust to the actual Chandra launcher)::

    vllm serve <chandra-model-id> --port 8230

which serves the model at ``http://127.0.0.1:8230/v1``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Callable, Optional

import httpx

from .config import ChandraConfig, ChandraError

logger = logging.getLogger(__name__)

# Bounded retry for transient vLLM failures (see ovisocr2 backend for rationale).
_VLLM_MAX_ATTEMPTS = 3
_VLLM_RETRY_BASE_DELAY = 1.0

# Generic end-to-end VLM OCR prompt. Chandra is a formula + handwriting + layout
# single model; the exact instruction wording can be refined per deployment via
# the engine's ``extra_prompt`` setting. We keep a neutral, output-format-explicit
# default rather than copying a model-card-specific prompt we don't have.
_DEFAULT_OCR_PROMPT = (
    "\nExtract all readable content from the image in natural human reading order "
    "and output the result as a single Markdown document. "
    "Format formulas as LaTeX. Format tables as HTML: <table>...</table>. "
    "Transcribe all handwriting and printed text as standard Markdown. "
    "Preserve the original text without translation or paraphrasing."
)


def _filter_bbox_imgtags(text: str) -> str:
    """Drop ``<img src="images/bbox_..." />`` visual-region blocks.

    Some VLM OCR models emit per-region bounding-box image links. DeepTutor does
    not crop region images, so those links would dangle — filter them out. This
    is a safe no-op for models that don't emit them.
    """
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
    """Trim degenerate repeated tails from long outputs (generic guard)."""
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
    """Page post-processing: strip → filter bbox tags → trim repeats."""
    return _clean_truncated_repeats(_filter_bbox_imgtags(text.strip()))


# -- probe ------------------------------------------------------------------


def probe_chandra_vllm(config: ChandraConfig) -> tuple[bool, str]:
    """Check whether the configured vLLM endpoint is reachable and serves
    the requested model. Returns ``(ok, message)``."""
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
        raise ChandraError(f"Cannot open PDF with PyMuPDF: {exc}") from exc

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
    config: ChandraConfig,
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
                    raise ChandraError(
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
                raise ChandraError(
                    f"vLLM returned HTTP {response.status_code} for page "
                    f"{png_path.name}: {snippet}"
                )
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                raise ChandraError(f"vLLM returned no choices for page {png_path.name}")
            return choices[0].get("message", {}).get("content", "") or ""
        raise ChandraError(
            f"vLLM returned HTTP {last_status} for page {png_path.name} "
            f"after {_VLLM_MAX_ATTEMPTS} attempts"
        )


# -- top-level parse entry point ---------------------------------------------


async def _parse_pages_async(
    pages: list[Path],
    config: ChandraConfig,
    on_output: Optional[Callable[[str], None]],
    *,
    prompt: str = _DEFAULT_OCR_PROMPT,
) -> list[str]:
    """Concurrent page processing with rate limiting."""
    sem = asyncio.Semaphore(config.max_concurrency)
    headers = {"Authorization": f"Bearer {config.api_token}"} if config.api_token else {}
    total = len(pages)

    async with httpx.AsyncClient(headers=headers) as client:
        async def _process_one(idx: int, png_path: Path) -> str:
            if on_output:
                on_output(f"Chandra parsing page {idx}/{total}...")
            try:
                md = await _call_vllm_page(client, png_path, config, sem, prompt=prompt)
            except ChandraError:
                raise
            except Exception as exc:
                raise ChandraError(
                    f"vLLM call failed for page {idx}/{total}: {exc}"
                ) from exc
            return _postprocess_page_markdown(md)

        return await asyncio.gather(
            *(_process_one(i, p) for i, p in enumerate(pages, 1))
        )


def _build_prompt(config: ChandraConfig) -> str:
    prompt = _DEFAULT_OCR_PROMPT
    if config.language and config.language.lower() != "auto":
        prompt += f"\n\nPreferred output language: {config.language}."
    if config.extra_prompt:
        prompt += f"\n\n{config.extra_prompt}"
    return prompt


def parse_pdf_via_chandra_vllm(
    source_path: Path,
    workdir: Path,
    *,
    config: ChandraConfig,
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
    """Loop-safe coroutine runner (mirrors deeptutor.services.embedding.client.embed_sync)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        return executor.submit(asyncio.run, coro).result()


__all__ = ["parse_pdf_via_chandra_vllm", "probe_chandra_vllm", "render_pdf_pages"]
