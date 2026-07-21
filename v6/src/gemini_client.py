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

from helper import cleanup_temp_files, load_config, pdf_to_images

# ---------------------------------------------------------------------------
# Import logger
# ---------------------------------------------------------------------------

from logger import get_logger
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Single, format-agnostic extraction config. The system_instruction, prompt,
# and response_schema live here rather than per-document-type files, since
# the pipeline now extracts the same four fields regardless of document type.
_PROJECT_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "configs", "extraction.json")

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GeminiClient:
    def __init__(
        self,
        api_key: str = os.getenv("GEMINI_API_KEY"),
        model_name: str = os.getenv("GEMINI_MODEL_NAME"),
    ):
        if not api_key:
            log.critical("GEMINI_API_KEY environment variable is not set.")
            raise ValueError("GEMINI_API_KEY environment variable is not set.")

        if not model_name:
            log.critical("GEMINI_MODEL_NAME environment variable is not set.")
            raise ValueError("GEMINI_MODEL_NAME environment variable is not set.")

        self.api_key    = api_key
        self.model_name = model_name

        self.client = genai.Client(api_key=self.api_key)
        self._auth()
        
    # ------------------------------------------------------------------
    # Authenticate API_KEY and MODEL_NAME
    # ------------------------------------------------------------------

    def _auth(self) -> None:
        try:
            models = list(self.client.models.list())
            model_names = [model.name.removeprefix("models/") for model in models]
            if self.model_name not in model_names:
                log.critical(
                    f"Gemini model '{self.model_name}' is not available.\n"
                    f"Available models: {model_names}"
                )
                raise ValueError(
                    f"Gemini model '{self.model_name}' is not available.\n"
                    f"Available models: {model_names}"
                )
            log.info(f"Gemini client initialised with model '{self.model_name}'.")
        except ValueError:
            raise
        except Exception as exc:
            log.critical(f"Gemini API key validation failed: {exc}")
            raise RuntimeError(f"Gemini API key validation failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Core LLM call
    # ------------------------------------------------------------------

    def call_llm(self, prompt: str, system_instruction: str, image_paths: list[str], response_schema: dict):
        contents = []
        for image_path in image_paths:
            if not os.path.exists(image_path):
                log.error(f"Image file not found: {image_path!r}\n"
                          "Ensure the path is correct and the file exists."
                )
                raise FileNotFoundError(
                    f"Image file not found: {image_path!r}\n"
                    "Ensure the path is correct and the file exists."
                )
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
            except Exception as exc:
                log.error(f"Could not read image file {image_path!r}: {exc}")
                raise IOError(f"Could not read image file {image_path!r}: {exc}") from exc

            ext = os.path.splitext(image_path)[1].lower()
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
            log.error(f"Gemini API call failed: {exc}")
            raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract_invoice_data(self, pdf_path: str, config_path: str = _DEFAULT_CONFIG_PATH) -> dict:
        prompt, system_instruction, response_schema, _ = load_config(config_path)

        temp_images: list[str] = []
        try:
            temp_images = pdf_to_images(pdf_path)
            response    = self.call_llm(prompt, system_instruction, temp_images, response_schema)
            log.debug(f"Gemini raw response: {response}")
        finally:
            if temp_images:
                cleanup_temp_files(temp_images)

        parsed = response.parsed
        if parsed is None:
            log.error(
                "Gemini returned no structured output. "
                "Check document quality, page count, or model configuration."
            )
            raise RuntimeError(
                "Gemini returned no structured output. "
                "Check document quality, page count, or model configuration."
            )
        return parsed