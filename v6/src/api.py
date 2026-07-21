#!/usr/bin/python3
"""
api.py — FastAPI endpoint for structured data extraction from PDF invoices.

Usage (start server):
    uvicorn api:app --host 0.0.0.0 --port 8000

Usage (PowerShell client):
    Invoke-WebRequest -Uri "http://localhost:8000/extract" `
        -Method POST `
        -Form @{ File = Get-Item "C:/Users/datacore/Downloads/tax_invoice.pdf" }

Install dependencies:
    pip install fastapi uvicorn python-dotenv pdf2image google-genai python-multipart
    # CORS is handled by Starlette's CORSMiddleware, included with fastapi.
"""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File as FastAPIFile, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gemini_client import _DEFAULT_CONFIG_PATH, GeminiClient
from helper import cleanup_temp_file, load_config, resolve_paths, _TEMP_DIR

# ---------------------------------------------------------------------------
# Import logger
# ---------------------------------------------------------------------------

from logger import get_logger
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Initialise GeminiClient and load extraction config
# ---------------------------------------------------------------------------

_client = GeminiClient()
_, _, _, _fields_of_interest = load_config(_DEFAULT_CONFIG_PATH)

# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown logging
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("HSL Invoice Extraction API is ready.")
    yield
    log.info("HSL Invoice Extraction API is shutting down.")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HSL Invoice Extraction API",
    description="Accepts a raw PDF body and returns structured JSON extracted by Gemini.",
    version="6.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_upload(pdf_bytes: bytes) -> str:
    os.makedirs(_TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(_TEMP_DIR, f"{uuid.uuid4().hex}_upload.pdf")

    try:
        with open(temp_path, "wb") as f:
            f.write(pdf_bytes)
        log.debug(f"Saved uploaded PDF to temporary file: {temp_path}")
    except OSError as exc:
        log.error(f"Failed to write temporary PDF file at {temp_path}: {exc}")
        raise RuntimeError(f"Failed to write temporary PDF file at {temp_path}: {exc}") from exc

    return temp_path

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", summary="Health check")
async def health_check() -> JSONResponse:
    return JSONResponse(content={"status": "ok"})


@app.post(
    "/extract",
    summary="Extract structured data from a PDF invoice",
    response_description="Structured JSON: company_name, invoice_no, po_no, subtotal",
)
async def extract(File: UploadFile = FastAPIFile(...)) -> JSONResponse:
    # 1. Validate Content-Type / filename extension
    is_pdf_content_type = File.content_type in ("application/pdf", "application/octet-stream")
    is_pdf_extension    = (File.filename or "").lower().endswith(".pdf")
    if not is_pdf_content_type and not is_pdf_extension:
        log.error(
            f"Expected a PDF file. "
            f"Got content-type {File.content_type!r} and filename {File.filename!r}."
        )
        raise HTTPException(
            status_code=415,
            detail=(
                f"Expected a PDF file. "
                f"Got content-type {File.content_type!r} and filename {File.filename!r}."
            ),
        )

    # 2. Read uploaded file
    _MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB
    pdf_bytes = await File.read(_MAX_UPLOAD_SIZE + 1)
    if not pdf_bytes:
        log.error("Uploaded file is empty. Send a valid PDF file.")
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty. Send a valid PDF file."
        )
    if len(pdf_bytes) > _MAX_UPLOAD_SIZE:
        log.error(f"Uploaded file exceeds maximum size of {_MAX_UPLOAD_SIZE} bytes.")
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds maximum size of {_MAX_UPLOAD_SIZE} bytes."
        )

    # 3. Save upload → run extraction → always clean up temp file
    temp_pdf: str = ""
    try:
        temp_pdf = _save_upload(pdf_bytes)
        result   = _client.extract_invoice_data(temp_pdf)

    except HTTPException:
        raise

    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    except (ImportError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    except Exception as exc:
        log.error(f"Extraction failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")

    finally:
        if temp_pdf:
            cleanup_temp_file(temp_pdf)

    # 4. Load fields_of_interest from the default config and resolve against the result.
    return JSONResponse(content=resolve_paths(result, _fields_of_interest))