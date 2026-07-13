# HSL Invoice Extraction API — V0

FastAPI service that accepts a PDF invoice, rasterises its first page, sends the image to Google Gemini, and returns structured JSON.

---

## Project structure

```
HSL/
├── src/
│   ├── __init__.py
│   ├── api.py
│   ├── gemini_client.py
│   └── helper.py
├── configs/
│   ├── tax_invoice.json
│   ├── zensus.json
│   └── system-solution.json
├── temp/                  # auto-created at runtime
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
└── requirements.txt
```

---

## Dependencies

```bash
pip install fastapi uvicorn python-dotenv pdf2image google-genai
```

Poppler must also be installed and available on `PATH`:

- Ubuntu/Debian: `sudo apt-get install poppler-utils`
- macOS: `brew install poppler`
- Windows: download Poppler and add its `bin/` directory to `PATH`

---

## Environment variables

Create a `.env` file in the project root:

```
GEMINI_API_KEY=<your-key>
GEMINI_MODEL_NAME=<model-identifier>
TEMP_DIR=<optional-custom-temp-path>
```

`TEMP_DIR` defaults to `HSL/temp/` if not set. Inside Docker it is set to `/app/temp` via the Dockerfile.

---

## Running locally

```bash
cd src/
uvicorn api:app --host 0.0.0.0 --port 8000
```

## Running with Docker

```bash
# Build and start
docker-compose up --build

# Stop
docker-compose down
```

The `.env` file is read at container startup via `env_file` in `docker-compose.yml`. It is never baked into the image.

A health check polls `http://localhost:8000/docs` every 30 seconds. The container is marked unhealthy after 3 consecutive failures.

---

## API

### `POST /extract`

Extracts structured data from a single-page PDF invoice.

**Request**

| Part | Requirement |
|---|---|
| `Content-Type` | `application/pdf` |
| `type` header | Document type identifier (see supported types below) |
| Body | Raw binary PDF content |

**Supported `type` header values**

| Value | Config file used |
|---|---|
| `tax-invoice` | `configs/tax_invoice.json` |
| `zensus` | `configs/zensus.json` |
| `system-solution` | `configs/system-solution.json` |

**PowerShell example**

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/extract" `
    -Method POST `
    -ContentType "application/pdf" `
    -Headers @{ "type" = "tax-invoice" } `
    -InFile "C:/Users/datacore/Downloads/tax_invoice.pdf"
```

**Response**

JSON object with fields defined by `fields_of_interest` in the relevant config file. Field values are `null` if absent or unreadable in the document.

**Error responses**

| Status | Reason |
|---|---|
| 400 | Missing, empty, or invalid `type` header; empty request body |
| 404 | Unrecognised document type |
| 415 | `Content-Type` is not `application/pdf` |
| 500 | Config file missing on disk; Gemini error; Poppler error |

---

## Config files

Each document type has its own `.json` config in `configs/`. The file must contain exactly three top-level keys:

```json
{
  "prompt": "Extract the following fields from this invoice...",
  "response_schema": {
    "type": "object",
    "properties": { ... }
  },
  "fields_of_interest": {
    "company_name": "letter_head.company_name",
    "invoice_no":   "invoice_details.invoice_no"
  }
}
```

| Key | Type | Purpose |
|---|---|---|
| `prompt` | string | Extraction instruction sent to Gemini with each image |
| `response_schema` | object | JSON schema that constrains Gemini's output |
| `fields_of_interest` | object | Maps output aliases to dot-path expressions in Gemini's response |

**Dot-path syntax**

- `"letter_head.company_name"` resolves `data["letter_head"]["company_name"]`
- `"line_items[0].hsn"` resolves `data["line_items"][0]["hsn"]`

Missing or unresolvable paths return `null` rather than raising an error.

**Adding a new document type**

1. Create `configs/<name>.json` with the three required keys.
2. Add an entry to `_SUPPORTED_TYPES` in `api.py`:
   ```python
   "my-type": "my_type.json",
   ```
3. No other code changes are needed.

---

## Processing pipeline

```
POST /extract
  → validate Content-Type and type header
  → save raw bytes to HSL/temp/<type>_upload.pdf
  → GeminiClient.extract_invoice_data(pdf_path, config_path)
      → load_config()      read and validate configs/<type>.json
      → pdf_to_image()     rasterise page 1 → HSL/temp/<stem>.jpg  (400 DPI)
      → call_llm()         send image + prompt to Gemini
      → cleanup temp image
  → cleanup temp PDF
  → resolve_paths()        flatten dot-paths to alias → value
  → JSONResponse
```

---

## Notes

- Only the first page of the PDF is processed. Multi-page documents are accepted but only page 1 is sent to Gemini.
- The system instruction ("expert document parser specialising in Indian tax invoices") is hardcoded in `gemini_client.py` and shared across all document types.
- Gemini is called with `temperature=0.1` and `thinking_budget=0` for deterministic, low-latency output.
- Concurrent requests using the same document type share the same temp PDF filename (`<type>_upload.pdf`). In production, run a single worker or add request-level locking to avoid collisions.