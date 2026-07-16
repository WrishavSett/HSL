# Changelog — Codebase 4 → Codebase 5

Changes are confined to `api.py` and `helper.py`. `gemini_client.py` and the Docker setup are unchanged.

---

## Changed behaviour

### `GeminiClient` and config initialised once at startup

`GeminiClient()` was previously instantiated on every request, and `load_config` was called twice per request — once inside `extract_invoice_data` and once in the `/extract` handler to retrieve `fields_of_interest`. Both are now initialised once at module level:

```python
# Before — per request
result = GeminiClient().extract_invoice_data(temp_pdf)
_, _, _, fields_of_interest = load_config(DEFAULT_CONFIG_PATH)

# After — once at startup
_client = GeminiClient()
_, _, _, _fields_of_interest = load_config(DEFAULT_CONFIG_PATH)
```

The `/extract` handler now calls `_client.extract_invoice_data(temp_pdf)` and uses the cached `_fields_of_interest` directly. As a side effect, if `GEMINI_API_KEY` is missing or the config is malformed, the server fails immediately at startup rather than returning a 500 on the first request.

### `normalize_subtotal` algorithm replaced

The Codebase 4 implementation used `re.search(r'[\d,]+\.\d+', value)` to locate a numeric pattern, then stripped commas from the match. This had two gaps:

- Whole numbers with no decimal point (e.g. `"₹ 500"`, `"1,00,000"`) matched nothing and were returned unchanged.
- Ambiguous multi-decimal strings like `"4.91.716.95"` would silently match and return the first `4.91`, which is incorrect.

The new implementation uses a four-step algorithm instead:

```python
normalize_subtotal("4,91,716.95")   → "491716.95"   # unchanged
normalize_subtotal("₹ 4,91,716.95") → "491716.95"   # unchanged
normalize_subtotal("1,00,000")      → "100000"       # now handled
normalize_subtotal("₹ 500")         → "500"          # now handled
normalize_subtotal("4.91.716.95")   → "4.91.716.95"  # now rejected correctly
normalize_subtotal("N/A")           → "N/A"          # unchanged
```

1. Find the first digit — if none exists, return the original value unchanged.
2. Find the last digit; take the substring spanning first-to-last, trimming leading symbols and trailing suffixes like `/-`.
3. Strip everything except digits and `.` from that span.
4. If more than one `.` remains, the input is ambiguous — return the original value unchanged.

---

## Internal changes

### `api.py`

- `GeminiClient()` moved to module-level singleton `_client`.
- `load_config` call moved to module level; result cached in `_fields_of_interest`.
- Version bumped from `2.0.0` to `5.0.0`.

### `helper.py`

- `normalize_subtotal` algorithm replaced (see above).
- `_SEGMENT` regex (used in `load_config` for path validation) lifted from inside the function body to module level, alongside the existing `_PATH_SEGMENT`.
- Module docstring reordered: `normalize_subtotal` and `resolve_paths` entries swapped to match the order they appear in the file.

### `gemini_client.py`

No changes.

### Docker

No changes.

---

## What did not change

- Multipart upload and PDF validation logic are retained.
- `parsed is None` guard is retained.
- `extract_invoice_data` still calls `load_config` internally — this is now redundant for the API's normal path but only matters if the method is called directly with a non-default config path.
- Image temp filename collision risk (same-named PDFs producing colliding `{stem}_p1.jpg` files) remains unaddressed.