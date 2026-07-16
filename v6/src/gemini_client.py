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

from errors import (
    GeminiAuthError,
    GeminiEmptyResponseError,
    ImageNotFoundError,
    ImageReadError,
    MissingAPIKeyError,
    MissingModelNameError,
    classify_gemini_error,
)
from helper import cleanup_temp_files, load_config, pdf_to_images

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_PROJECT_ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "configs", "extraction.json")

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GeminiClient:
    """
    Client for extracting structured data from invoice images via Gemini.

    The system_instruction, prompt, and response_schema are loaded from a
    single .json config file at runtime (see DEFAULT_CONFIG_PATH),
    keeping this class document-format agnostic.

    Attributes:
        api_key (str):         Gemini API key.
        model_name (str):      Gemini model identifier.
        client (genai.Client): Initialised Gemini API client.
    """

    def __init__(
        self,
        api_key: str   = os.getenv("GEMINI_API_KEY"),
        model_name: str = os.getenv("GEMINI_MODEL_NAME"),
    ):
        """
        Initialise the Gemini client.

        Args:
            api_key (str):    API key for Gemini authentication.
                              Defaults to the GEMINI_API_KEY env variable.
            model_name (str): Gemini model name to use for generation.
                              Defaults to the GEMINI_MODEL_NAME env variable.

        Raises:
            MissingAPIKeyError   : If api_key is None or empty.
            MissingModelNameError: If model_name is None or empty.
            GeminiAuthError      : If the google-genai SDK rejects the key at
                                   client construction time.
        """
        if not api_key:
            raise MissingAPIKeyError(
                detail=(
                    f"GEMINI_API_KEY is not set or is empty.\n"
                    "Set it in your .env file or as an environment variable."
                )
            )

        if not model_name:
            raise MissingModelNameError(
                detail=(
                    f"GEMINI_MODEL_NAME is not set or is empty.\n"
                    "Set it in your .env file or as an environment variable."
                )
            )

        self.api_key    = api_key
        self.model_name = model_name

        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            raise GeminiAuthError(
                detail=(
                    f"The google-genai SDK rejected the API key at client initialisation: {exc}\n"
                    "Verify that GEMINI_API_KEY is correct and has not been revoked."
                )
            )

    # ------------------------------------------------------------------
    # Core LLM call
    # ------------------------------------------------------------------

    def call_llm(
        self,
        prompt: str,
        system_instruction: str,
        image_paths: list[str],
        response_schema: dict,
    ):
        """
        Send images + prompt to Gemini and return the raw API response.

        Args:
            prompt (str):              Per-call trigger instruction for the model.
            system_instruction (str):  Persona and field-extraction rules for the model.
            image_paths (list[str]):   Paths to image files to analyse, one per page, in order.
            response_schema (dict):    JSON schema that constrains model output.

        Returns:
            genai.types.GenerateContentResponse:
                Raw response. Use .parsed for a structured dict or
                .text for the raw JSON string.

        Raises:
            ImageNotFoundError : If any path in image_paths does not exist.
            ImageReadError     : If any image file cannot be read.
            HSLError           : Classified Gemini API error via classify_gemini_error().
        """
        contents = []
        for image_path in image_paths:
            if not os.path.exists(image_path):
                raise ImageNotFoundError(
                    detail=(
                        f"Image file not found: {image_path!r}\n"
                        "Ensure the path is correct and the file exists."
                    )
                )
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
            except Exception as exc:
                raise ImageReadError(
                    detail=f"Could not read image file {image_path!r}: {exc}"
                )

            ext       = os.path.splitext(image_path)[1].lower()
            mime_type = "image/png" if ext == ".png" else "image/jpeg"
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
        contents.append(prompt)

        try:
            return self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    system_instruction=system_instruction,
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )
        except Exception as exc:
            raise classify_gemini_error(exc)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract_invoice_data(self, pdf_path: str, config_path: str = DEFAULT_CONFIG_PATH) -> dict:
        """
        Extract structured data (company_name, invoice_no, po_no, subtotal)
        from a single- or multi-page PDF, format-agnostic across document types.

        The PDF is rasterised into temporary JPEGs stored in HSL/temp/.
        Temporary images are always deleted on exit, even if an error occurs.

        Args:
            pdf_path (str):    Path to the single- or multi-page PDF document.
            config_path (str): Path to the .json config file. Defaults to
                               configs/extraction.json.

        Returns:
            dict: Parsed JSON response — company_name, invoice_no, po_no, subtotal.

        Raises:
            HSLError : Any error from config loading, PDF conversion, image I/O,
                       or the Gemini API, each carrying its specific code and description.

        Example:
            >>> client = GeminiClient()
            >>> data = client.extract_invoice_data("data/tax_invoice.pdf")
        """
        prompt, system_instruction, response_schema, _ = load_config(config_path)

        temp_images: list[str] = []
        try:
            temp_images = pdf_to_images(pdf_path)
            response    = self.call_llm(prompt, system_instruction, temp_images, response_schema)
        finally:
            if temp_images:
                cleanup_temp_files(temp_images)

        parsed = response.parsed
        if parsed is None:
            raise GeminiEmptyResponseError(
                detail=(
                    "Gemini returned no structured output. "
                    "Check document quality, page count, or model configuration."
                )
            )
        return parsed