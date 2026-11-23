import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


def get_setting(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value:
        return value

    try:
        secret = st.secrets.get(name)
    except StreamlitSecretNotFoundError:
        return default
    return str(secret) if secret else default
