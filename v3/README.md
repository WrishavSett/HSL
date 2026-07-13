# Changelog — V2 → V3

This release changes the upload mechanism from a raw `application/pdf` request body to `multipart/form-data`, and adds CORS support for browser-based clients. Changes are confined to `api.py`. `helper.py`, `gemini_client.py`, and the Docker setup are unchanged.

---

## Breaking changes

### Upload method changed: raw body → multipart form

The endpoint no longer accepts a raw PDF body. The file must now be sent as `multipart/form-data` with a field named `File`.

Before:
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/extract" `
    -Method POST `
    -ContentType "application/pdf" `
    -InFile "C:/Users/datacore/Downloads/tax_invoice.pdf"
```

After:
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/extract" `
    -Method POST `
    -Form @{ File = Get-Item "C:/Users/datacore/Downloads/tax_invoice.pdf" }
```

The form field name is case-sensitive: `File` (capital F).

### New dependency: `python-multipart`

FastAPI requires `python-multipart` to parse `multipart/form-data`. Add it to your environment and to `requirements.txt`:

```bash
pip install python-multipart
```

---

## New features

### CORS support

`CORSMiddleware` is now registered on the app, enabling requests from browser-based frontends:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
    allow_credentials=False,
)
```

All origins are permitted. If deploying to production, restrict `allow_origins` to the specific frontend domain.

### Relaxed PDF validation

Previously the `Content-Type` header had to be exactly `application/pdf`. Validation is now OR-based: the file is accepted if either condition is true:

- Content type is `application/pdf` or `application/octet-stream`
- Filename ends with `.pdf`

This accommodates clients (including most browsers) that send `application/octet-stream` for binary file uploads regardless of actual format. Note that a non-PDF file named with a `.pdf` extension will pass validation.

---

## Internal changes

### `api.py`

- Imports: `Request`, `Header` removed; `UploadFile`, `File as FastAPIFile`, `CORSMiddleware` added.
- Route signature: `async def extract(request: Request)` → `async def extract(File: UploadFile = FastAPIFile(...))`.
- PDF bytes now read with `await File.read()` instead of `await request.body()`.
- Validation checks `File.content_type` and `File.filename` instead of the raw `content-type` header.
- `python-multipart` added to install instructions in module docstring.

### `helper.py`

No changes.

### `gemini_client.py`

No changes.

### Docker

No changes. `Dockerfile`, `docker-compose.yml`, and `.dockerignore` are identical to Codebase 2.

---

## What did not change

- Multi-page processing is retained.
- `parsed is None` guard is retained.
- `load_config` is still called twice per request.
- `GeminiClient.__init__` still raises `ImportError` for credential errors.
- Image temp filenames still use `{stem}_p{n}.jpg` — the partial collision risk for concurrent uploads of same-named files remains.