# HSL Invoice Extraction API

A FastAPI service that accepts a PDF invoice, rasterises it, sends it to Google Gemini for vision-based extraction, and returns structured JSON. Extraction behaviour — what to extract and how to structure the output — is driven entirely by config files, keeping the application code document-agnostic.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & How It Works](#2-architecture--how-it-works)
3. [Project Structure](#3-project-structure)
4. [Codebase Walkthrough](#4-codebase-walkthrough)
5. [Local Setup](#5-local-setup)
6. [Docker Setup](#6-docker-setup)
7. [Testing the API using Postman](#7-testing-the-api-using-postman)
8. [Config Files](#8-config-files)
9. [API Reference](#9-api-reference)
10. [Environment Variables](#10-environment-variables)

---

## 1. Project Overview

HSL provides a single HTTP endpoint — `POST /extract` — that:

1. Accepts a PDF invoice as an upload.
2. Rasterises each page to a JPEG image using **pdf2image** (Poppler).
3. Sends the images and an extraction prompt to **Google Gemini**, which returns a structured JSON object constrained by a predefined schema.
4. Resolves a configured set of fields of interest from the full response and returns them to the caller.

**Tech stack**

| Layer             | Technology                    |
|-------------------|-------------------------------|
| Web framework     | FastAPI + Uvicorn             |
| LLM / vision      | Google Gemini (`google-genai`)|
| PDF rasterisation | pdf2image + Poppler           |
| Config format     | Plain JSON                    |
| Containerisation  | Docker + Docker Compose       |

---

## 2. Architecture & How It Works

```
Client
  │
  │  POST /extract
  │  Body: <PDF bytes>
  │
  ▼
api.py  ──►  Validates the uploaded file
        ──►  Saves PDF to temp/
        ──►  Calls GeminiClient.extract_invoice_data()
                │
                ├─ helper.load_config()        Loads system instruction, prompt,
                │                              schema, and fields of interest
                ├─ helper.pdf_to_images()      Rasterises all pages → JPEGs
                ├─ GeminiClient.call_llm()     Sends images + prompt to Gemini
                ├─ helper.cleanup_temp_files() Deletes temp JPEGs
                │
                └─ Returns response.parsed (full dict)
        ──►  helper.resolve_paths()   Resolves dot-path fields of interest
        ──►  Returns JSONResponse
```

**Config-driven design.** A `.json` config file in `configs/` defines the system instruction (Gemini's persona and extraction rules), the per-call prompt, the JSON Schema constraining Gemini's output, and the `fields_of_interest` dot-path map that filters the response down to the fields the caller needs. No application code needs to change to alter extraction behaviour or add new document types.

**Temp file lifecycle.** The uploaded PDF and all rasterised page images are written to `HSL/temp/` (or `/app/temp/` in Docker) and are unconditionally deleted in `finally` blocks, even when errors occur.

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
│   └── extraction.json     # System instruction, prompt, schema, fields of interest
│
├── src/
│   ├── __init__.py
│   ├── api.py              # FastAPI app and /extract endpoint
│   ├── gemini_client.py    # GeminiClient — LLM calls and PDF extraction
│   ├── helper.py           # Shared utilities (config, PDF to image, cleanup, resolve)
│   └── logger.py           # Centralised logger file
└── temp/                   # Transient scratch space for PDF and image files
```

---

## 4. Codebase Walkthrough

### `src/api.py`

The FastAPI application. Exposes two routes:

**`GET /`**

- Health check

**`POST /extract`**

- Validates the uploaded file by checking its content type and filename extension.
- Saves the raw PDF bytes to a UUID-named temp file via `_save_upload()`, preventing filename collisions on concurrent requests.
- Instantiates `GeminiClient` and calls `extract_invoice_data()`.
- Loads `fields_of_interest` from the config and passes the result through `resolve_paths()` to produce the final flat response dict.
- Cleans up the temp PDF in a `finally` block regardless of success or failure.

---

### `src/gemini_client.py`

Contains `GeminiClient`, the sole interface to the Gemini API.

**`__init__(api_key, model_name)`** — Reads credentials from environment variables (`GEMINI_API_KEY`, `GEMINI_MODEL_NAME`) and initialises a `genai.Client`.

**`_auth(self)`** — Validates the API key and confirms the requested model is available.

**`call_llm(prompt, system_instruction, image_paths, response_schema)`** — Reads each page image from disk, assembles them into a single `contents` list, appends the prompt, and sends the request to Gemini. Key generation settings:

| Setting               | Value              | Reason                                               |
|-----------------------|--------------------|------------------------------------------------------|
| `temperature`         | `0.1`              | Near-deterministic output for structured extraction  |
| `response_mime_type`  | `application/json` | Forces JSON output                                   |
| `response_schema`     | from config        | Constrains field names and types                     |
| `thinking_budget`     | `0`                | Disables chain-of-thought to reduce latency and cost |

**`extract_invoice_data(pdf_path, config_path)`** — Orchestrates the full extraction pipeline: loads config → rasterises all PDF pages → calls `call_llm` → deletes temp images → validates and returns `response.parsed`.

---

### `src/helper.py`

Shared utilities used by both `api.py` and `gemini_client.py`.

**`load_config(config_path)`** — Reads and validates a `.json` config file. Raises `FileNotFoundError` if the path is wrong, `ValueError` if the JSON is malformed, if required keys are missing, or if any value is empty or of the wrong type.

**`pdf_to_images(pdf_path, temp_dir, dpi, fmt, max_pages)`** — Rasterises all pages of a PDF using `pdf2image` (Poppler's `pdftoppm`). Returns a list of image paths, one per page, in order. Raises `ValueError` if the page count exceeds `max_pages` (default 30).

**`cleanup_temp_file(path)` / `cleanup_temp_files(paths)`** — Deletes one or more files, silently ignoring missing-file errors.

**`normalize_subtotal(subtotal)`** — Strips non-numeric characters from a raw subtotal string.

**`resolve_paths(data, fields_of_interest)`** — Walks a set of dot-path expressions against the parsed Gemini response dict and returns a flat alias → value mapping. Missing or unresolvable paths return `null` rather than raising an error.

---

### `configs/extraction.json`

Defines how Gemini processes documents. Contains four top-level keys:

| Key                  | Type   | Purpose                                                            |
|----------------------|--------|--------------------------------------------------------------------|
| `system_instruction` | string | Persona and extraction rules given to Gemini as context            |
| `prompt`             | string | Per-call instruction sent alongside the document image(s)          |
| `response_schema`    | object | JSON Schema constraining Gemini's output structure and field types |
| `fields_of_interest` | object | Alias → dot-path map of fields to extract from the full response   |

**Dot-path syntax**

Paths in `fields_of_interest` use dot-separated keys with optional array indices:

- `"letter_head.company_name"` → `data["letter_head"]["company_name"]`
- `"line_items[0].hsn"` → `data["line_items"][0]["hsn"]`

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

```
GEMINI_API_KEY=your-gemini-api-key-here
GEMINI_MODEL_NAME=gemini-3.1-flash-lite
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

The API will be available at `http://localhost:8000`. Interactive docs (Swagger UI) are served at `http://localhost:8000/docs`.

---

## 6. Docker Setup

### Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose plugin)

### Steps

**1. Create the `.env` file** (same as local setup above)

**2. Build and start the container**

```bash
docker compose up --build
```

The `--build` flag forces Docker to rebuild the image. Omit it on subsequent starts if nothing has changed.

**3. Verify the container is healthy**

Docker Compose is configured with a health check that polls `http://localhost:8000/docs` every 30 seconds. Once the container status shows `healthy`, the API is ready:

```bash
docker ps
# CONTAINER ID   IMAGE                    STATUS
# abc123...      hsl-invoice-api:latest   Up 2 minutes (healthy)
```

**4. Stop the container**

```bash
docker compose down
```

**5. Rebuild after code or config changes**

```bash
docker compose up --build
```

### Notes

- Secrets are injected at runtime via `env_file: .env` in `docker-compose.yml`. They are never baked into the image.
- The Docker image is based on `python:3.11-slim`. Poppler (`poppler-utils`) is installed as a system dependency during the build.
- `requirements.txt` is copied and installed before application files to exploit Docker layer caching — dependencies are only reinstalled when `requirements.txt` changes.
- Temp files are written to `/app/temp/` inside the container, controlled by the `TEMP_DIR` environment variable set in the Dockerfile.
- The container is configured with `restart: unless-stopped` and will automatically restart after a Docker daemon restart unless explicitly stopped.

---

## 7. Testing the API using Postman

Postman is a convenient way to test the `/extract` endpoint without writing any code.

### Steps

**1. Set the method and URL**

- Method: `POST`
- URL: `http://localhost:8000/extract`

**2. Attach the PDF**

- Open the **Body** tab.
- Select **form-data**.
- Add a key named `File`, set its type to **File**, and select your PDF (e.g. `test_data/tax_invoice.pdf`).

**3. Send the request**

Click **Send**. A successful extraction returns HTTP `200` with a JSON body containing the fields defined in `fields_of_interest`:

```json
{
  "company_name": "DCG Data-Core Systems (India) Private Limited",
  "invoice_no": "DC/25-26/03/0020",
  "po_no": "DB&FP/1011/PO2/2025-26",
  "subtotal": "13,92,000.00"
}
```

Fields absent or unreadable in the document are returned as `null`.

### Troubleshooting

| Symptom                      | Likely cause                                | Fix                                                                                       |
|------------------------------|---------------------------------------------|-------------------------------------------------------------------------------------------|
| `415 Unsupported Media Type` | File type not recognised                    | Ensure the file has a `.pdf` extension and the field type is set to **File** in form-data |
| `400 Bad Request`            | Uploaded file is empty                      | Confirm the file is a valid, non-empty PDF                                                |
| `500 Internal Server Error`  | Server-side error (Gemini, Poppler, config) | Check the server logs for the full error message                                          |

---

## 8. Config Files

Extraction behaviour is controlled entirely by JSON config files in `configs/`. The config defines what Gemini is told, what structure it must return, and which fields from that structure are included in the API response.

### Required keys

```json
{
  "system_instruction": "You are an expert financial-document parser.\n...",
  "prompt": "The following images are the pages of a single document, presented...",
  "response_schema": {
    "type": "object",
    "properties": {
      "company_name": { "type": "string", "description": "" },
      "invoice_no":   { "type": "string", "description": "" },
      "po_no":        { "type": "string", "description": "" },
      "subtotal":     { "type": "string", "description": "" }
    },
    "required": ["company_name", "invoice_no", "po_no", "subtotal"],
        "propertyOrdering": ["company_name", "invoice_no", "po_no", "subtotal"]
  },
  "fields_of_interest": {
    "company_name": "company_name",
    "invoice_no":   "invoice_no",
    "po_no":        "po_no",
    "subtotal":     "subtotal"
  }
}
```

| Key                  | Purpose                                                           |
|----------------------|-------------------------------------------------------------------|
| `system_instruction` | Sets Gemini's persona and global extraction rules                 |
| `prompt`             | Per-request instruction accompanying the document                 |
| `response_schema`    | JSON Schema that constrains Gemini's output; guarantees structure |
| `fields_of_interest` | Maps response alias names to dot-paths in Gemini's full output    |

Modifying the config file is the only change needed to alter what fields are extracted or how Gemini is instructed to behave.

---

## 9. API Reference

### `POST /extract`

Accepts a PDF upload and returns structured JSON.

**Request**

The endpoint accepts `multipart/form-data` with a single file field:

| Field  | Type | Required | Description                                                                                                                               |
|--------|------|----------|-------------------------------------------------------------------------------------------------------------------------------------------|
| `File` | file | Yes      | The PDF to extract data from. Validated by content type (`application/pdf`, `application/octet-stream`) and/or `.pdf` filename extension. |

**Response — `200 OK`**

A flat JSON object with one key per entry in `fields_of_interest`. Field values are `null` if absent or unreadable in the document.

```json
{
  "company_name": "DCG Data-Core Systems (India) Private Limited",
  "invoice_no": "DC/25-26/03/0020",
  "po_no": "DB&FP/1011/PO2/2025-26",
  "subtotal": "13,92,000.00"
}
```

**Error responses**

| Status | Reason                                                                                    |
|--------|-------------------------------------------------------------------------------------------|
| `400`  | Uploaded file is empty                                                                    |
| `415`  | File is not a PDF (wrong content type and no `.pdf` extension)                            |
| `500`  | Config missing on disk, Gemini API error, Poppler error, or no structured output returned |

**Interactive docs**

Swagger UI is available at `http://localhost:8000/docs` when the server is running.

---

## 10. Environment Variables

| Variable            | Required | Description                                                                                                           |
|---------------------|----------|-----------------------------------------------------------------------------------------------------------------------|
| `GEMINI_API_KEY`    | Yes      | API key for authenticating with the Google Gemini API                                                                 |
| `GEMINI_MODEL_NAME` | Yes      | Gemini model identifier, e.g. `gemini-2.5-flash-preview`                                                              |
| `TEMP_DIR`          | No       | Directory for transient PDF and image files. Defaults to `HSL/temp/` locally; set to `/app/temp/` in the Docker image |

All variables are read from the `.env` file in the project root via `python-dotenv`. In Docker they are injected through the `env_file` directive in `docker-compose.yml`.