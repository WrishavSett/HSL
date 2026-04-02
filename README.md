# HSL Invoice Extraction API

A FastAPI service that accepts a raw PDF invoice, rasterises it, and returns structured JSON extracted by Google Gemini. Document schemas and prompts are driven entirely by config files, so new document types can be added without touching application code.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & How It Works](#2-architecture--how-it-works)
3. [Project Structure](#3-project-structure)
4. [Codebase Walkthrough](#4-codebase-walkthrough)
5. [Local Setup](#5-local-setup)
6. [Docker Setup](#6-docker-setup)
7. [Testing the API using Postman](#7-testing-the-api-using-postman)
8. [Adding a New Document Type](#8-adding-a-new-document-type)
9. [API Reference](#9-api-reference)
10. [Environment Variables](#10-environment-variables)

---

## 1. Project Overview

HSL provides a single HTTP endpoint — `POST /extract` — that:

1. Accepts the raw binary content of a PDF invoice.
2. Converts the first page to a JPEG image using **pdf2image** (Poppler).
3. Sends the image and an extraction prompt to **Google Gemini**, which returns a JSON object conforming to a predefined schema.
4. Filters the full response down to a small set of fields of interest and returns them to the caller.

**Tech stack**

| Layer | Technology |
|---|---|
| Web framework | FastAPI + Uvicorn |
| LLM / vision | Google Gemini (`google-genai`) |
| PDF rasterisation | pdf2image + Poppler |
| Config format | Plain JSON (prompt + JSON Schema) |
| Containerisation | Docker + Docker Compose |

---

## 2. Architecture & How It Works

```
Client
  │
  │  POST /extract
  │  Content-Type: application/pdf
  │  Header: type = tax-invoice
  │  Body: <raw PDF bytes>
  │
  ▼
api.py  ──►  Validates Content-Type & type header
        ──►  Writes PDF to HSL/temp/<type>_upload.pdf
        ──►  Calls GeminiClient.extract_invoice_data()
                │
                ├─ helper.load_config()       Loads prompt + schema from configs/
                ├─ helper.pdf_to_image()      Rasterises PDF → JPEG (400 dpi)
                ├─ GeminiClient.call_llm()    Sends image + prompt to Gemini
                └─ helper.cleanup_temp_file() Deletes temp JPEG
                │
                └─ Returns response.parsed (full dict)
        ──►  helper.search_fields()  Extracts fields of interest
        ──►  Returns JSONResponse
```

**Config-driven design.** Each document type maps to a `.json` file in `configs/`. The file contains two keys: `"prompt"` (extraction instructions) and `"response_schema"` (a JSON Schema that Gemini uses to constrain its output). Adding a new document type requires only a new config file and a one-line entry in `api.py` — no other code changes are needed.

**Temp file lifecycle.** Both the uploaded PDF and the converted JPEG are written to `HSL/temp/` (or `/app/temp/` in Docker) and are unconditionally deleted in `finally` blocks, even when errors occur.

---

## 3. Project Structure

```
HSL/
├── .dockerignore           # Files excluded from the Docker build context
├── .env                    # Runtime secrets — never committed to version control
├── .gitignore
├── docker-compose.yml      # Single-service Compose definition
├── Dockerfile              # python:3.11-slim + Poppler + app files
├── requirements.txt        # Pinned Python dependencies
│
├── configs/
│   └── tax_invoice.json    # Prompt + JSON Schema for TAX INVOICE documents
│
├── src/
│   ├── __init__.py
│   ├── api.py              # FastAPI app and /extract endpoint
│   ├── gemini_client.py    # GeminiClient — LLM calls and PDF extraction
│   └── helper.py           # Shared utilities (config, PDF→image, cleanup, search)
│
├── temp/                   # Transient scratch space for PDF and image files
│                           # (auto-created at runtime; contents are not committed)
└── test_data/
    └── tax_invoice.pdf     # Sample invoice for manual testing
```

---

## 4. Codebase Walkthrough

### `src/api.py`

The FastAPI application. It exposes one route:

**`POST /extract`**

- Validates that `Content-Type` is `application/pdf` (→ HTTP 415 if not).
- Reads the `type` request header and calls `_resolve_config()`, which maps the header value to a config file path. Returns HTTP 400 for a missing/malformed header, HTTP 404 for an unknown type, and HTTP 500 if the config file is registered but absent from disk.
- Saves the raw PDF bytes to a temp file via `_save_upload()`.
- Instantiates `GeminiClient` and calls `extract_invoice_data()`.
- Passes the full response through `search_fields()` and returns only the fields listed in `_FIELDS_OF_INTEREST`.
- Cleans up the temp PDF in a `finally` block regardless of success or failure.

**To change which fields are returned**, edit `_FIELDS_OF_INTEREST` in `api.py`:

```python
_FIELDS_OF_INTEREST: list[str] = [
    "company_name",
    "invoice_no",
    "order_no",
    "total_amount_before_tax",
]
```

---

### `src/gemini_client.py`

Contains `GeminiClient`, the sole interface to the Gemini API.

**`__init__(api_key, model_name)`** — Reads credentials from environment variables (`GEMINI_API_KEY`, `GEMINI_MODEL_NAME`) and initialises a `genai.Client`.

**`call_llm(prompt, image_path, response_schema)`** — Reads the JPEG from disk, sends it to Gemini alongside the prompt, and returns the raw API response. Key generation settings:

| Setting | Value | Reason |
|---|---|---|
| `temperature` | `0.1` | Near-deterministic output for structured extraction |
| `response_mime_type` | `application/json` | Forces JSON output |
| `response_schema` | from config | Constrains field names and types |
| `thinking_budget` | `0` | Disables chain-of-thought to reduce latency and cost |

**`extract_invoice_data(pdf_path, config_path)`** — Orchestrates the full pipeline: loads config → converts PDF to JPEG → calls `call_llm` → deletes the JPEG → returns `response.parsed` (a Python dict).

---

### `src/helper.py`

Shared utilities used by both `api.py` and `gemini_client.py`.

**`load_config(config_path)`** — Reads and validates a `.json` config file. Raises `FileNotFoundError` if the path is wrong, `ValueError` if the JSON is malformed, if required keys (`"prompt"`, `"response_schema"`) are missing, or if either value is empty.

**`pdf_to_image(pdf_path, temp_dir, dpi, fmt)`** — Rasterises the first page of a PDF using `pdf2image` (which wraps Poppler's `pdftoppm`). Defaults to 400 dpi JPEG. The higher DPI significantly improves Gemini's OCR accuracy on dense invoice layouts.

**`cleanup_temp_file(path)`** — Deletes a file, silently ignoring the case where the file no longer exists.

**`search_fields(data, fields)`** — Recursively walks a nested dict/list structure and returns the first value found for each requested field name, regardless of nesting depth. This makes it resilient to schema changes — `"invoice_no"` will be found whether it lives under `invoice_details` or at the top level.

---

### `configs/tax_invoice.json`

Defines how Gemini should process a tax invoice. It has two top-level keys:

- **`"prompt"`** — A plain-English instruction telling Gemini what to extract.
- **`"response_schema"`** — A JSON Schema object. Gemini uses this to constrain its output, guaranteeing that the response matches the expected structure. The schema for `tax_invoice.json` covers: letter head, invoice details, receiver and consignee details, order details, line items, tax breakup, payment mode, certification statement, authorised signatory, and registered office address.

---

## 5. Local Setup

### Prerequisites

- Python 3.11 or later
- Poppler (required by `pdf2image` at runtime)

**Install Poppler:**

```bash
# Ubuntu / Debian
sudo apt-get install poppler-utils

# macOS
brew install poppler

# Windows
# Download from https://github.com/oschwartz10612/poppler-windows/releases
# Extract and add the bin/ folder to your PATH
```

### Steps

**1. Clone the repository**

```bash
git clone <repository-url>
cd HSL
```

**2. Create the `.env` file**

```bash
# HSL/.env
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL_NAME=gemini-2.5-flash-preview
```

> `.env` is listed in `.gitignore` and must never be committed to version control.

**3. Create and activate a virtual environment**

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

**4. Install dependencies**

```bash
pip install -r requirements.txt
```

**5. Start the server**

```bash
cd src
uvicorn api:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs are served at `http://localhost:8000/docs`.

**6. Send a test request (PowerShell)**

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/extract" `
    -Method POST `
    -ContentType "application/pdf" `
    -Headers @{ "type" = "tax-invoice" } `
    -InFile "test_data/tax_invoice.pdf"
```

**Expected response:**

```json
{
  "company_name": "DCG Data-Core Systems (India) Private Limited",
  "invoice_no": "DC/25-26/03/0020",
  "order_no": "DB&FP/1011/PO2/2025-26",
  "total_amount_before_tax": "13,92,000.00"
}
```

---

## 6. Docker Setup

### Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose plugin)

### Steps

**1. Create the `.env` file** (same as the local setup step above)

```bash
# HSL/.env
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL_NAME=gemini-2.5-flash-preview
```

**2. Build and start the container**

```bash
docker compose up --build
```

The `--build` flag forces Docker to (re)build the image. Omit it on subsequent starts if nothing has changed.

**3. Verify the container is healthy**

Docker Compose is configured with a health check that polls `http://localhost:8000/docs` every 30 seconds. Once the container status shows `healthy`, the API is ready:

```bash
docker ps
# CONTAINER ID   IMAGE                    STATUS
# abc123...      hsl-invoice-api:latest   Up 2 minutes (healthy)
```

**4. Send a test request (PowerShell)**

```powershell
Invoke-WebRequest -Uri "http://localhost:8000/extract" `
    -Method POST `
    -ContentType "application/pdf" `
    -Headers @{ "type" = "tax-invoice" } `
    -InFile "test_data/tax_invoice.pdf"
```

**5. Stop the container**

```bash
docker compose down
```

**6. Rebuild after code changes**

```bash
docker compose up --build
```

### Notes

- Secrets are injected at runtime via `env_file: .env` in `docker-compose.yml`. They are never baked into the image.
- Temp files are written to `/app/temp/` inside the container (controlled by the `TEMP_DIR` environment variable set in the Dockerfile).
- The container is configured with `restart: unless-stopped`, so it will automatically restart after a Docker daemon restart unless explicitly stopped.

---

## 7. Testing the API using Postman

Postman is a convenient way to test the `/extract` endpoint without writing any code. The request requires three things: the correct HTTP method, a `type` header, and the PDF sent as a binary body.

### Steps

**1. Set the method and URL**

- Method: `POST`
- URL: `http://localhost:8000/extract`

**2. Add the `type` header**

Open the **Headers** tab and add:

| Key | Value |
|---|---|
| `type` | `tax-invoice` |

> Do not set `Content-Type` manually — Postman sets it automatically when you select binary body in the next step.

**3. Attach the PDF as the request body**

- Open the **Body** tab.
- Select **binary**.
- Click **Select File** and choose your PDF (e.g. `test_data/tax_invoice.pdf`).

Postman will automatically set `Content-Type: application/pdf` based on the file extension.

**4. Send the request**

Click **Send**. A successful extraction returns HTTP `200` with a JSON body:

```json
{
  "company_name": "DCG Data-Core Systems (India) Private Limited",
  "invoice_no": "DC/25-26/03/0020",
  "order_no": "DB&FP/1011/PO2/2025-26",
  "total_amount_before_tax": "13,92,000.00"
}
```

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `415 Unsupported Media Type` | Postman sent the wrong `Content-Type` | Ensure **binary** is selected in the Body tab, not `form-data` or `raw` |
| `400 Bad Request` | `type` header is missing or empty | Confirm the header key is exactly `type` (lowercase) |
| `404 Not Found` | Unrecognised document type | Check the `type` header value matches a key in `_SUPPORTED_TYPES` (e.g. `tax-invoice`) |
| `500 Internal Server Error` | Server-side error (Gemini, Poppler, missing config) | Check the server logs for the full error message |

---

## 8. Adding a New Document Type

**Step 1 — Create a config file**

Add a new `.json` file to `configs/`. It must follow this structure:

```json
{
    "prompt": "Extract all data from this <DOCUMENT TYPE> and return it as a valid JSON object that strictly conforms to the provided schema.",

    "response_schema": {
        "type": "object",
        "properties": {
            "field_one": { "type": "string" },
            "field_two": { "type": "string" }
        },
        "required": ["field_one", "field_two"]
    }
}
```

**Step 2 — Register the type in `api.py`**

Add a single entry to the `_SUPPORTED_TYPES` dict:

```python
_SUPPORTED_TYPES: dict[str, str] = {
    "tax-invoice":    "tax_invoice.json",
    "purchase-order": "purchase_order.json",   # ← new entry
}
```

The key is the value callers pass in the `type` header. The value is the filename inside `configs/`.

**Step 3 — Update fields of interest (optional)**

If the new document type introduces fields you want returned, add them to `_FIELDS_OF_INTEREST`:

```python
_FIELDS_OF_INTEREST: list[str] = [
    "company_name",
    "invoice_no",
    "order_no",
    "total_amount_before_tax",
    "po_number",               # ← new field
]
```

`search_fields()` performs a deep recursive search, so the field just needs to exist somewhere in the schema — its nesting depth does not matter.

No other changes are required.

---

## 9. API Reference

### `POST /extract`

Accepts a raw PDF body and returns structured JSON.

**Request headers**

| Header | Required | Description |
|---|---|---|
| `Content-Type` | Yes | Must be `application/pdf` |
| `type` | Yes | Document type identifier, e.g. `tax-invoice` |

**Request body**

Raw binary content of a single-page PDF file.

**Response — `200 OK`**

```json
{
  "company_name": "DCG Data-Core Systems (India) Private Limited",
  "invoice_no": "DC/25-26/03/0020",
  "order_no": "DB&FP/1011/PO2/2025-26",
  "total_amount_before_tax": "13,92,000.00"
}
```

Fields absent from the extracted document are returned as `null`.

**Error responses**

| Status | Reason |
|---|---|
| `400` | Missing or empty `type` header, invalid characters in header, or empty request body |
| `404` | Unrecognised document type |
| `415` | `Content-Type` is not `application/pdf` |
| `500` | Config file missing on disk, Gemini API error, or Poppler/pdf2image failure |

**Interactive docs**

When the server is running, full interactive documentation (Swagger UI) is available at:

```
http://localhost:8000/docs
```

---

## 10. Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | API key for authenticating with the Google Gemini API |
| `GEMINI_MODEL_NAME` | Yes | Gemini model identifier, e.g. `gemini-2.5-flash-preview` |
| `TEMP_DIR` | No | Directory for transient PDF and image files. Defaults to `HSL/temp/` locally and is set to `/app/temp/` in the Docker image |

All variables are read from the `.env` file in the project root via `python-dotenv`. In Docker they are injected through the `env_file` directive in `docker-compose.yml`.