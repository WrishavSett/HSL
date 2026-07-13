# Changelog — V0 → V1

This release collapses per-document-type routing into a single, format-agnostic extraction pipeline. The `type` header and per-type config files are removed. One config file now drives every request.

Docker support is intentionally dropped in this version.

---

## Breaking changes

### `type` request header removed

The `type` header is no longer required or accepted. All requests use the same extraction config regardless of document type.

Before:
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/extract" `
    -Method POST `
    -ContentType "application/pdf" `
    -Headers @{ "type" = "tax-invoice" } `
    -InFile "invoice.pdf"
```

After:
```powershell
Invoke-WebRequest -Uri "http://localhost:8000/extract" `
    -Method POST `
    -ContentType "application/pdf" `
    -InFile "invoice.pdf"
```

### Per-type config files replaced by a single universal config

`configs/tax_invoice.json`, `configs/zensus.json`, and `configs/system-solution.json` are no longer used. A single `configs/extraction.json` is now the only config file.

### `load_config` return signature changed

`load_config` now returns a 4-tuple instead of 3:

```python
# Before
(prompt, response_schema, fields_of_interest)

# After
(prompt, system_instruction, response_schema, fields_of_interest)
```

Any code calling `load_config` directly must be updated.

### Docker setup removed

`Dockerfile`, `docker-compose.yml`, and `.dockerignore` are not present in this version. Run the server locally only:

```bash
cd src/
uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## New features

### `system_instruction` moved from hardcoded constant to config

Previously `_SYSTEM_INSTRUCTION` was a hardcoded string in `gemini_client.py`. It is now a `"system_instruction"` key in `configs/extraction.json`, making it editable without touching code.

### UUID-based temp PDF filenames

Temp PDF files are now named `<uuid>_upload.pdf` instead of `<type>_upload.pdf`. This eliminates the concurrency collision risk where simultaneous requests of the same type would overwrite each other's temp file.

Before:
```
HSL/temp/tax-invoice_upload.pdf
```

After:
```
HSL/temp/3f2a1b4c8e...d7_upload.pdf
```

---

## Updated config format

`configs/extraction.json` requires four top-level keys instead of three:

```json
{
  "system_instruction": "You are an expert document parser...",
  "prompt": "Extract the following fields...",
  "response_schema": {
    "type": "object",
    "properties": { ... }
  },
  "fields_of_interest": {
    "company_name": "letter_head.company_name",
    "invoice_no":   "invoice_details.invoice_no",
    "po_no":        "invoice_details.po_no",
    "subtotal":     "tax_breakup.total_amount_before_tax"
  }
}
```

| Key | Type | Purpose |
|---|---|---|
| `system_instruction` | string | Persona and extraction rules for Gemini (previously hardcoded) |
| `prompt` | string | Per-call trigger instruction |
| `response_schema` | object | JSON schema constraining Gemini output |
| `fields_of_interest` | object | Alias → dot-path map of fields to return |

---

## Internal changes

### `api.py`

- `_SUPPORTED_TYPES`, `_CONFIGS_DIR`, and `_resolve_config()` removed entirely.
- `_save_upload()` no longer accepts a `doc_type` argument; uses `uuid.uuid4().hex` for the filename.
- Route handler no longer declares a `type: str = Header(...)` parameter.
- `GeminiClient().extract_invoice_data()` is now called without a `config_path` argument; the client uses `DEFAULT_CONFIG_PATH` internally.
- `load_config` is still called a second time in the route handler to retrieve `fields_of_interest` after extraction. This is a known redundancy.

### `gemini_client.py`

- `_SYSTEM_INSTRUCTION` constant removed.
- `DEFAULT_CONFIG_PATH` added, pointing to `configs/extraction.json`.
- `extract_invoice_data` `config_path` argument now has a default of `DEFAULT_CONFIG_PATH` (was mandatory).
- `call_llm` now accepts `system_instruction` as a parameter instead of using the module-level constant.
- `load_config` unpacking updated to 4-tuple.

### `helper.py`

- `load_config` updated to require and validate `"system_instruction"` as a fourth config key.
- Return signature changed from `(prompt, response_schema, fields_of_interest)` to `(prompt, system_instruction, response_schema, fields_of_interest)`.

---

## What did not change

- Single-page processing only — page 1 of the PDF is still the only page sent to Gemini.
- `pdf_to_image`, `cleanup_temp_file`, and `resolve_paths` are unchanged.
- Image temp filenames still use `{pdf_stem}.jpg`, so concurrent requests uploading files with the same original filename will still collide on the image temp file.
- DPI remains 400.
- `GeminiClient.__init__` still raises `ImportError` for credential errors.
- `load_config` is still called twice per request.