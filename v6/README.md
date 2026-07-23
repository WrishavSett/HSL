# Changelog — Codebase 5 → Codebase 6

Changes are confined to `api.py`, `gemini_client.py`, and `helper.py`. Docker is unchanged.

---

## New module

### `logger.py` — centralised rotating-file logger

A new `logger.py` module introduces a single named logger (`"hsl"`) shared
across all pipeline modules. It attaches two handlers at import time — a
`StreamHandler` for console output and a `RotatingFileHandler` writing to
`logs/hsl.log` (5 MB cap, 5 backups). All three existing modules now import
and use it:

```python
from logger import get_logger
log = get_logger(__name__)
```

Child loggers (e.g. `hsl.api`, `hsl.helper`, `hsl.gemini_client`) inherit
the root `"hsl"` logger's handlers, so there is no duplicate output.
Propagation to the root logger is explicitly disabled.

---

## Changed behaviour

### `GeminiClient.__init__` — startup validation replaced

The v5 constructor wrapped `genai.Client(api_key=...)` in a broad
`try/except` and raised `ImportError` on failure regardless of the actual
cause. Missing or empty env vars were not caught until the client call
itself.

v6 replaces this with explicit guards before the client is created, and
raises `ValueError` (not `ImportError`) for missing credentials:

```python
# Before — broad catch, wrong exception type
try:
    self.client = genai.Client(api_key=self.api_key)
except Exception:
    if self.api_key is not None:
        raise ImportError("API key not configured properly.")
    raise ImportError("API key not provided.")

# After — explicit guards, correct exception types
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set.")
if not model_name:
    raise ValueError("GEMINI_MODEL_NAME environment variable is not set.")
self.client = genai.Client(api_key=self.api_key)
self._auth()
```

### `GeminiClient._auth` — new method for model validation

v5 created the `genai.Client` and immediately started using it with no
verification that the configured model actually exists. v6 introduces a
private `_auth()` method called at the end of `__init__`. It lists all
models accessible with the API key and confirms `model_name` is among them:

```python
models = list(self.client.models.list())
model_names = [model.name.removeprefix("models/") for model in models]
if self.model_name not in model_names:
    raise ValueError(
        f"Gemini model '{self.model_name}' is not available.\n"
        f"Available models: {model_names}"
    )
```

If the model is valid, `_auth` logs an `INFO` message confirming the client
is ready. If the `models.list()` call itself fails for a reason other than an
invalid model name, a `RuntimeError` is raised.

### `DEFAULT_CONFIG_PATH` renamed to `_DEFAULT_CONFIG_PATH`

The module-level config path constant in `gemini_client.py` has been made
private to signal it is an implementation detail rather than a public API.
`api.py` is updated to import the renamed symbol:

```python
# Before
DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "configs", "extraction.json")
from gemini_client import DEFAULT_CONFIG_PATH, GeminiClient

# After
_DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "configs", "extraction.json")
from gemini_client import _DEFAULT_CONFIG_PATH, GeminiClient
```

### `GeminiClient.call_llm` — unhandled API exceptions now caught

v5 called `client.models.generate_content` with no exception handling,
so any network error, quota error, or schema error would propagate as an
untyped exception. v6 wraps the call and re-raises as `RuntimeError`:

```python
# Before — bare call, no error handling
return self.client.models.generate_content(...)

# After — exceptions caught and re-raised with context
try:
    return self.client.models.generate_content(...)
except Exception as exc:
    log.error(f"Gemini API call failed: {exc}")
    raise RuntimeError(f"Gemini API call failed: {exc}") from exc
```

### `api.py` — 20 MB upload size limit enforced

v5 read the entire upload into memory with `await File.read()` regardless
of size. v6 introduces a 20 MB cap, reading at most `_MAX_UPLOAD_SIZE + 1`
bytes so that an over-limit upload can be detected without consuming the
full stream, and returns HTTP 413 if the limit is exceeded:

```python
# Before — unbounded read
pdf_bytes = await File.read()

# After — bounded read + size check
_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB
pdf_bytes = await File.read(_MAX_UPLOAD_SIZE + 1)
if len(pdf_bytes) > _MAX_UPLOAD_SIZE:
    raise HTTPException(status_code=413, detail=f"Uploaded file exceeds maximum size ...")
```

### `api.py` — `_save_upload` now raises `RuntimeError` on write failure

v5 had no error handling around the `open` call in `_save_upload`, so an
`OSError` (e.g. permission denied or disk full) would propagate unhandled
and surface as an uncaught 500. v6 wraps the write and raises `RuntimeError`
explicitly, which the `/extract` handler's `except (ImportError, RuntimeError)`
clause already catches and maps to a 500 with a meaningful message:

```python
# Before — unguarded write
with open(temp_path, "wb") as f:
    f.write(pdf_bytes)

# After — guarded write
try:
    with open(temp_path, "wb") as f:
        f.write(pdf_bytes)
except OSError as exc:
    raise RuntimeError(f"Failed to write temporary PDF file at {temp_path}: {exc}") from exc
```

### `api.py` — FastAPI lifespan replaces bare module-level startup

v5 initialised `_client` and `_fields_of_interest` at module level with no
lifecycle hooks. v6 introduces a proper `lifespan` async context manager
(using `asynccontextmanager`) that logs startup and shutdown events and is
passed to the `FastAPI` constructor. The module-level initialisations are
retained but moved above the `lifespan` definition:

```python
# Before — no lifespan, no lifecycle logging
app = FastAPI(..., version="5.0.0")

# After — lifespan with logging
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("HSL Invoice Extraction API is ready.")
    yield
    log.info("HSL Invoice Extraction API is shutting down.")

app = FastAPI(..., version="6.0.0", lifespan=lifespan)
```

---

## Internal changes

### `api.py`

- `asynccontextmanager` imported from `contextlib` for the lifespan handler.
- Logger imported and used in `_save_upload`, `extract` (415, 400, 413
  validation branches, and the generic exception branch).
- Version bumped from `5.0.0` to `6.0.0`.

### `gemini_client.py`

- Logger imported and used in `__init__` (critical on missing credentials),
  `_auth` (critical on bad model name, info on success, critical on API
  failure), `call_llm` (error on missing image, error on unreadable image,
  error on API failure), and `extract_invoice_data` (debug for raw response,
  error for `None` parsed result).

### `helper.py`

- Logger imported and used in `pdf_to_images` (error for missing PDF, debug
  after successful conversion, error for `PDFInfoNotInstalledError`, error
  for `PDFPageCountError`, error for generic conversion failure, critical for
  page-count exceeded), `cleanup_temp_file` (debug after successful deletion),
  and `normalize_subtotal` (debug when multiple decimal points are found).

### Docker

No changes.

---

## What did not change

- The `normalize_subtotal` algorithm is unchanged from v5.
- The `resolve_paths` traversal logic is unchanged.
- The `load_config` validation logic is unchanged.
- The multipart upload and PDF content-type/extension validation logic in
  `extract` are unchanged.
- The `parsed is None` guard in `extract_invoice_data` is retained.
- The module-level singleton pattern for `_client` and `_fields_of_interest`
  introduced in v5 is retained.
- Image temp filename collision risk (same-named PDFs producing colliding
  `{stem}_p1.jpg` files) remains unaddressed.