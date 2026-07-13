# Changelog — V1 → V2

This release adds multi-page PDF support and reintroduces Docker. All pages of a PDF are now rasterised and sent to Gemini in a single call. A page limit guard is also added to prevent runaway memory use on large uploads.

No breaking changes to the API surface. `api.py` has only a documentation update.

---

## New features

### Multi-page PDF support

Previously only the first page of a PDF was rasterised and sent to Gemini. All pages are now processed.

`pdf_to_image` (singular, returns `str`) is replaced by `pdf_to_images` (plural, returns `list[str]`). Each page is saved as a separate JPEG named `{stem}_p{n}.jpg`:

```
HSL/temp/3f2a1b4c..._upload_p1.jpg
HSL/temp/3f2a1b4c..._upload_p2.jpg
HSL/temp/3f2a1b4c..._upload_p3.jpg
```

All page images are sent to Gemini in a single `generate_content` call, with each page appended as a `Part.from_bytes` before the prompt string.

### Page limit guard

`pdf_to_images` now accepts a `max_pages` parameter (default `30`). If the PDF exceeds this limit, a `ValueError` is raised after conversion:

```
ValueError: PDF has 47 pages, which exceeds the limit of 30.
Split the document or raise max_pages.
```

### `parsed is None` guard in `extract_invoice_data`

If Gemini returns a response with no structured output, `response.parsed` is `None`. Previously this `None` was silently returned to the caller. Now a `RuntimeError` is raised:

```
RuntimeError: Gemini returned no structured output.
Check document quality, page count, or model configuration.
```

### MIME type inference in `call_llm`

`call_llm` previously hardcoded `mime_type="image/jpeg"` for all images. It now infers the correct MIME type from the file extension:

```python
mime_type = "image/png" if ext == ".png" else "image/jpeg"
```

### `cleanup_temp_files` (plural)

A new `cleanup_temp_files(paths: list[str])` helper is added to `helper.py`. It iterates over a list of paths and calls the existing `cleanup_temp_file` on each. The original single-file function is preserved unchanged.

---

## Docker reintroduced

Docker support returns after being dropped in Codebase 1. Three files are added: `Dockerfile`, `docker-compose.yml`, and `.dockerignore`.

**Image:** `python:3.11-slim` with `poppler-utils`, `gcc`, and `libffi-dev` installed via `apt`.

**Directory layout inside the container:**

```
/app/
├── src/       ← application source; WORKDIR at runtime
├── configs/   ← extraction config
└── temp/      ← rasterised image scratch space
```

**Key behaviours:**

- `requirements.txt` is copied and installed before application files to exploit Docker layer caching.
- `TEMP_DIR=/app/temp` is set in the Dockerfile, overriding the default `_PROJECT_ROOT`-relative path calculated in `helper.py`.
- `PYTHONUNBUFFERED=1` ensures logs are not buffered inside the container.
- Secrets are passed at runtime via `env_file: .env` in `docker-compose.yml` and are never baked into the image.
- A health check polls `http://localhost:8000/docs` every 30 seconds, with a 15-second startup grace period and 3 retries before the container is marked unhealthy.

**Running with Docker:**

```bash
# Build and start
docker-compose up --build

# Stop
docker-compose down
```

**`.dockerignore` excludes:**

- `.venv/`, `__pycache__/`, `*.pyc`, `*.pyo`, `*.pyd`
- `temp/` — ephemeral scratch files
- `.env`, `*.env` — secrets
- `.git/`, `.gitignore`
- `.DS_Store`, `*.swp`, `Thumbs.db`

---

## Changed defaults

| Parameter | Before | After |
|---|---|---|
| DPI | 400 | 200 |

Lower DPI reduces memory use and processing time. 200 DPI is sufficient for printed invoice text. Increase if OCR accuracy degrades on dense or small-print documents.

---

## Partially fixed: image temp file collision

In Codebase 1, image temp files used `{stem}.jpg` where the stem came from the original PDF filename. Two concurrent requests uploading a file called `invoice.pdf` would collide on `HSL/temp/invoice.jpg`.

The new per-page naming (`{stem}_p{n}.jpg`) does not fully resolve this — the stem is still derived from the PDF filename, not from the UUID. Concurrent requests with identically named uploads still collide on the image files. The PDF temp file itself uses a UUID and is safe.

---

## Internal changes

### `helper.py`

- `pdf_to_image(pdf_path, ...) -> str` replaced by `pdf_to_images(pdf_path, ..., max_pages=30) -> list[str]`.
- Output filenames changed from `{stem}.{ext}` to `{stem}_p{i}.{ext}` (1-indexed).
- `max_pages` validation runs after conversion (Poppler must read the file to count pages).
- `cleanup_temp_files(paths: list[str])` added.

### `gemini_client.py`

- `call_llm` signature: `image_path: str` → `image_paths: list[str]`.
- `call_llm` builds `contents` by looping over `image_paths`, then appends the prompt string last.
- `extract_invoice_data` calls `pdf_to_images` and `cleanup_temp_files`.
- `temp_image: str` → `temp_images: list[str]`.
- `parsed is None` check added after `response.parsed`.

### `api.py`

- Docstring: `single-page PDF` → `single- or multi-page PDF`. No logic changes.

---

## What did not change

- API request/response format is identical.
- `load_config`, `resolve_paths`, `_TEMP_DIR` unchanged.
- `load_config` still called twice per request.
- `GeminiClient.__init__` still raises `ImportError` for credential errors.
- No CORS middleware.
- Upload method remains raw `application/pdf` body.