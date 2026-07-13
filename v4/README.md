# Changelog — Codebase 3 → Codebase 4

This release adds subtotal normalisation, a health check endpoint, and broadens CORS method coverage. Changes are confined to `api.py` and `helper.py`. `gemini_client.py` and the Docker setup are unchanged.

---

## New features

### Subtotal normalisation

Gemini can return subtotal values in inconsistent formats depending on how the source document prints them — with currency symbols, Indian-style grouping commas, suffixes, or surrounding whitespace. A new `normalize_subtotal` function in `helper.py` handles this by locating the numeric pattern directly and discarding everything else:

```python
normalize_subtotal("4,91,716.95")     → "491716.95"
normalize_subtotal("₹ 4,91,716.95")  → "491716.95"
normalize_subtotal("Rs. 4,91,716.95") → "491716.95"
normalize_subtotal("4,91,716.95/-")   → "491716.95"
normalize_subtotal("N/A")             → "N/A"   # returned unchanged
```

Rather than stripping known prefixes or suffixes, it uses `re.search(r'[\d,]+\.\d+', value)` to locate the numeric portion and removes grouping commas from the match. If no numeric pattern is found, the original value is returned unchanged.

Normalisation is applied automatically inside `resolve_paths` when the alias is `"subtotal"` and the resolved value is a string:

```python
if alias == "subtotal" and isinstance(node, str):
    node = normalize_subtotal(node)
```

No changes to the config or the caller are required.

### Health check endpoint

A `GET /` endpoint is added to `api.py`:

```python
@app.get("/", summary="Health check")
async def health_check() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})
```

**Response — `200 OK`**

```json
{ "status": "ok" }
```

This provides a lightweight liveness check that does not touch Gemini, Poppler, or the config, making it suitable for load balancers and uptime monitors.

---

## Changed behaviour

### CORS `allow_methods` broadened

`allow_methods` in `CORSMiddleware` is changed from `["POST"]` to `["*"]`:

```python
# Before
allow_methods=["POST"],

# After
allow_methods=["*"],
```

This is consistent with the new `GET /` endpoint — the previous `["POST"]` would have blocked browser preflight and `GET` requests from cross-origin clients.

---

## Internal changes

### `helper.py`

- `normalize_subtotal(value: str) -> str` added.
- `resolve_paths` updated to call `normalize_subtotal` when `alias == "subtotal"` and the resolved value is a string.
- Module docstring updated to list `normalize_subtotal` under provided utilities.

### `api.py`

- `GET /` health check route added.
- `allow_methods=["POST"]` → `allow_methods=["*"]`.

### `gemini_client.py`

No changes.

### Docker

No changes. `Dockerfile`, `docker-compose.yml`, and `.dockerignore` are identical to Codebase 3.

---

## What did not change

- Multipart upload and PDF validation logic are retained.
- `parsed is None` guard is retained.
- `load_config` is still called twice per request.
- `GeminiClient.__init__` still raises `ImportError` for credential errors.
- Image temp filenames still use `{stem}_p{n}.jpg` — the partial collision risk for concurrent uploads of same-named files remains.