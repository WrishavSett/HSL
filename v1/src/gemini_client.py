#!/usr/bin/python3
"""
gemini_client.py — Gemini API client for structured invoice data extraction.

Depends on helper.py for config loading, PDF conversion, and temp file cleanup.

Install dependencies:
    pip install google-genai python-dotenv pdf2image
"""

import os

from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
    from google.genai import types
except ImportError:
    raise ImportError("Please run `pip install google-genai` to use the Gemini client.")

from helper import cleanup_temp_file, load_config, pdf_to_image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Single, format-agnostic extraction config. The system_instruction, prompt,
# and response_schema live here rather than per-document-type files, since
# the pipeline now extracts the same four fields regardless of document type.
_PROJECT_ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "configs", "extraction.json")

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GeminiClient:
    """
    Client for extracting structured data from invoice images via Gemini.

    The system_instruction, prompt, and response_schema are loaded from a
    single .json config file at runtime (see ``DEFAULT_CONFIG_PATH``),
    keeping this class document-format agnostic.

    Attributes:
        api_key (str):         Gemini API key.
        model_name (str):      Gemini model identifier.
        client (genai.Client): Initialised Gemini API client.
    """

    def __init__(
        self,
        api_key: str = os.getenv("GEMINI_API_KEY"),
        model_name: str = os.getenv("GEMINI_MODEL_NAME"),
    ):
        """
        Initialise the Gemini client.

        Args:
            api_key (str):    API key for Gemini authentication.
                              Defaults to the ``GEMINI_API_KEY`` env variable.
            model_name (str): Gemini model name to use for generation.
                              Defaults to the ``GEMINI_MODEL_NAME`` env variable.

        Raises:
            ImportError: If the API key is missing or the client cannot initialise.
        """
        self.api_key    = api_key
        self.model_name = model_name

        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception:
            if self.api_key is not None:
                raise ImportError("API key not configured properly.")
            raise ImportError("API key not provided.")

    # ------------------------------------------------------------------
    # Core LLM call
    # ------------------------------------------------------------------

    def call_llm(self, prompt: str, system_instruction: str, image_path: str, response_schema: dict):
        """
        Send an image + prompt to Gemini and return the raw API response.

        Args:
            prompt (str):              Per-call trigger instruction for the model.
            system_instruction (str):  Persona and field-extraction rules for the model.
            image_path (str):          Path to the image file to analyse.
            response_schema (dict):    JSON schema that constrains model output.

        Returns:
            genai.types.GenerateContentResponse:
                Raw response. Use ``.parsed`` for a structured dict or
                ``.text`` for the raw JSON string.

        Raises:
            FileNotFoundError : If *image_path* does not exist.
            IOError           : If the image file cannot be read.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(
                f"Image file not found: {image_path!r}\n"
                "Ensure the path is correct and the file exists."
            )

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except Exception as exc:
            raise IOError(f"Could not read image file {image_path!r}: {exc}")

        return self.client.models.generate_content(
            model=self.model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt,
            ],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                system_instruction=system_instruction,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract_invoice_data(self, pdf_path: str, config_path: str = DEFAULT_CONFIG_PATH) -> dict:
        """
        Extract structured data (company_name, invoice_no, po_no, subtotal)
        from a single-page PDF, format-agnostic across document types.

        The PDF is rasterised into a temporary JPEG stored in ``HSL/temp/``.
        The temporary image is always deleted on exit, even if an error occurs.

        Args:
            pdf_path (str):    Path to the single-page PDF document.
            config_path (str): Path to the .json config file containing
                               ``"system_instruction"``, ``"prompt"``, and
                               ``"response_schema"``. Defaults to the single
                               universal ``configs/extraction.json``.

        Returns:
            dict: Parsed JSON response — company_name, invoice_no, po_no, subtotal.

        Raises:
            FileNotFoundError : If *pdf_path* or *config_path* does not exist.
            ValueError        : If the config file is malformed or missing keys.
            ImportError       : If ``pdf2image`` is not installed.
            RuntimeError      : If Poppler is missing or PDF conversion fails.
            IOError           : If the converted image file cannot be read.

        Example:
            >>> client = GeminiClient()
            >>> data = client.extract_invoice_data("data/tax_invoice.pdf")
        """
        prompt, system_instruction, response_schema, _ = load_config(config_path)

        temp_image: str = ""
        try:
            temp_image = pdf_to_image(pdf_path)
            response   = self.call_llm(prompt, system_instruction, temp_image, response_schema)
        finally:
            if temp_image:
                cleanup_temp_file(temp_image)

        return response.parsed