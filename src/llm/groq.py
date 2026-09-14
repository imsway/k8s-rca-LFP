import os

from langchain_groq import ChatGroq

DEFAULT_MODEL = "openai/gpt-oss-20b"


def get_groq_model(temperature: float = 0.1) -> ChatGroq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")
    model_name = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    return ChatGroq(model=model_name, api_key=api_key, temperature=temperature)
