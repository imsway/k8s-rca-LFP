import logging
import os
import warnings

from langchain_google_genai import ChatGoogleGenerativeAI

DEFAULT_MODEL = "gemini-3.1-flash-lite"

warnings.filterwarnings("ignore", message=".*automatic function calling.*AFC.*")
warnings.filterwarnings("ignore", message=".*Direct use of automatic function calling.*")
logging.getLogger("google.genai.models").setLevel(logging.ERROR)


def get_gemini_model(temperature: float = 0.1) -> ChatGoogleGenerativeAI:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    model_name = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
    )
