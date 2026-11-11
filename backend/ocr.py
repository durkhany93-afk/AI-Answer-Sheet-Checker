import os
import mimetypes

from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables from .env
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH, override=True)

_client = None


def client():
    """Initialize the Gemini API client."""
    global _client

    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()

        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is missing. Check your .env file."
            )

        _client = genai.Client(api_key=api_key)

    return _client


def model_name():
    """Return the configured Gemini model."""
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()


def extract_text(path):
    """Extract text from an uploaded answer-sheet image."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Image file not found: {path}")

    mime = mimetypes.guess_type(path)[0] or "image/jpeg"

    with open(path, "rb") as file:
        image_data = file.read()

    response = client().models.generate_content(
        model=model_name(),
        contents=[
            types.Part.from_bytes(
                data=image_data,
                mime_type=mime,
            ),
            (
                "Transcribe all visible text on this answer sheet exactly "
                "as written. Preserve question numbers, spelling, and "
                "line breaks as much as possible. Do not grade the answers. "
                "Return only the transcription."
            ),
        ],
    )

    if not response.text:
        raise ValueError("Gemini returned an empty OCR response.")

    return response.text.strip()