#!/usr/bin/python3
"""
gemini_client.py
================

Google Gemini API client for structured invoice data extraction.

Wraps the ``google-genai`` SDK to provide a thin, opinionated interface for
the HSL Invoice Extraction pipeline.  On instantiation the client validates
the supplied API key and model name against the live Gemini model list.  The
public entry point :meth:`GeminiClient.extract_invoice_data` accepts a path
to a PDF file, converts it to images via :func:`helper.pdf_to_images`, sends
all page images together with the configured prompt to the Gemini API, and
returns the structured dict from ``response.parsed``.

Dependencies
------------
- ``google-genai`` — Gemini API SDK.
- ``python-dotenv`` — Load ``GEMINI_API_KEY`` and ``GEMINI_MODEL_NAME`` from
  a ``.env`` file.
- ``pdf2image`` — PDF-to-image conversion (see ``helper.py`` for Poppler
  requirements).

Install
-------
::

    pip install google-genai python-dotenv pdf2image

Environment Variables
---------------------
``GEMINI_API_KEY``
    Required.  A valid Google Gemini API key.
``GEMINI_MODEL_NAME``
    Required.  The Gemini model identifier to use (e.g.
    ``"gemini-2.0-flash"``).  Must be present in the list returned by
    ``client.models.list()``.
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
    """
    Authenticated Gemini API client for structured invoice data extraction.

    On construction the client validates the API key by listing available
    models and confirms that the requested model is among them.  All
    subsequent calls reuse the same :class:`google.genai.Client` session.

    Parameters
    ----------
    api_key : str, optional
        Gemini API key.  Defaults to the ``GEMINI_API_KEY`` environment
        variable.
    model_name : str, optional
        Gemini model identifier.  Defaults to the ``GEMINI_MODEL_NAME``
        environment variable.

    Raises
    ------
    ValueError
        If ``api_key`` or ``model_name`` is empty, or if ``model_name`` is
        not in the list of available Gemini models.
    RuntimeError
        If the Gemini API key validation request fails for any reason other
        than an invalid model name.

    Example
    -------
    ::

        client = GeminiClient()
        result = client.extract_invoice_data("/invoices/invoice_001.pdf")
        # {"company_name": "Acme Corp", "invoice_no": "INV-0042", ...}
    """

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
        """
        Validate the API key and confirm the requested model is available.

        Lists all models accessible with the supplied API key and checks that
        ``self.model_name`` appears in the returned list (with the
        ``"models/"`` prefix stripped).  Called automatically by
        :meth:`__init__`.

        Raises
        ------
        ValueError
            If ``self.model_name`` is not found in the list of available
            models.
        RuntimeError
            If the ``client.models.list()`` call fails for any reason other
            than an unavailable model name.
        """
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

    def call_llm(
        self,
        prompt: str,
        system_instruction: str,
        image_paths: list[str],
        response_schema: dict,
    ):
        """
        Send a multi-image prompt to the Gemini API and return the raw response.

        Reads each file in ``image_paths`` into memory, wraps it as a
        ``types.Part`` with the appropriate MIME type, appends the text
        ``prompt``, and calls ``client.models.generate_content`` with JSON
        output constrained by ``response_schema``.  Thinking is disabled
        (``thinking_budget=0``) and temperature is fixed at ``0.1`` for
        deterministic extraction.

        Parameters
        ----------
        prompt : str
            Text instruction appended after all image parts in the content
            list.
        system_instruction : str
            System-level instruction passed via
            ``GenerateContentConfig.system_instruction``.
        image_paths : list[str]
            Ordered list of absolute paths to image files (JPEG or PNG) that
            represent the PDF pages to analyse.
        response_schema : dict
            JSON Schema dict that constrains the structure of the model's
            response.  Passed to ``GenerateContentConfig.response_schema``.

        Returns
        -------
        google.genai.types.GenerateContentResponse
            The raw response object from the Gemini API.  Access structured
            output via ``response.parsed``.

        Raises
        ------
        FileNotFoundError
            If any path in ``image_paths`` does not exist on disk.
        IOError
            If any image file in ``image_paths`` cannot be read.
        RuntimeError
            If the Gemini API call fails for any reason (network error,
            quota exceeded, invalid schema, etc.).

        Example
        -------
        ::

            response = client.call_llm(
                prompt="Extract invoice fields.",
                system_instruction="You are an invoice parser.",
                image_paths=["/tmp/invoice_p1.jpg"],
                response_schema={"type": "object", "properties": {...}},
            )
            data = response.parsed
        """
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

    def extract_invoice_data(
        self,
        pdf_path: str,
        config_path: str = _DEFAULT_CONFIG_PATH,
    ) -> dict:
        """
        Extract structured invoice data from a PDF file.

        Loads the extraction configuration from ``config_path``, converts the
        PDF at ``pdf_path`` to a list of page images via
        :func:`helper.pdf_to_images`, sends all images and the configured
        prompt to the Gemini API via :meth:`call_llm`, and returns the
        structured output from ``response.parsed``.  Temporary image files
        are always deleted in a ``finally`` block regardless of success or
        failure.

        Parameters
        ----------
        pdf_path : str
            Absolute or relative path to the PDF invoice to process.
        config_path : str, optional
            Path to the JSON extraction configuration file.  Defaults to
            ``<project_root>/configs/extraction.json``.

        Returns
        -------
        dict
            Structured extraction result as returned by ``response.parsed``.
            The exact shape is governed by the ``response_schema`` in the
            config file.

        Raises
        ------
        FileNotFoundError
            If ``pdf_path`` or ``config_path`` does not exist on disk.
        ValueError
            If the config file is invalid (see :func:`helper.load_config`).
        RuntimeError
            If the Gemini API call fails or if ``response.parsed`` is
            ``None`` (indicating no structured output was returned).

        Example
        -------
        ::

            client = GeminiClient()
            data = client.extract_invoice_data("/invoices/invoice_001.pdf")
            # {"vendor": {"name": "Acme Corp"}, "invoice": {"number": "INV-0042"}, ...}
        """
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