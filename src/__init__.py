"""
Invoice Processing Pipeline
===========================

Top-level package for the HSL Invoice Extraction pipeline.

This package exposes the FastAPI application, the Gemini API client, and shared
utility helpers used to extract structured data (company name, invoice number,
PO number, and subtotal) from PDF invoices via Google Gemini.

Modules
-------
api
    FastAPI application and HTTP endpoint definitions.
gemini_client
    Google Gemini API client for structured invoice data extraction.
helper
    Shared utilities: config loading, PDF-to-image conversion, temp file
    cleanup, subtotal normalisation, and dot-path field resolution.
logger
    Centralised rotating-file and console logger for the pipeline.
error
    Custom exception hierarchy for all pipeline errors.
"""