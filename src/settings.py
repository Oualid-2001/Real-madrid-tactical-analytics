import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
RETIRED_GEMINI_MODELS = {"gemini-2.5-flash"}


def get_setting(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value:
        return value

    try:
        secret = st.secrets.get(name)
    except StreamlitSecretNotFoundError:
        return default
    return str(secret) if secret else default


def get_gemini_model() -> str:
    model = get_setting("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    if model in RETIRED_GEMINI_MODELS:
        return DEFAULT_GEMINI_MODEL
    return model or DEFAULT_GEMINI_MODEL
