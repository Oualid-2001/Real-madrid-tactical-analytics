from pathlib import Path

import requests
from dotenv import load_dotenv

from src.settings import get_setting

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

API_KEY = get_setting("GEMINI_API_KEY")
MODEL = get_setting("GEMINI_MODEL", "gemini-2.5-flash")

API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/"
    f"models/{MODEL}:generateContent"
)


def generate_tactical_analysis(match_data: str) -> str:
    if not API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Set it in .env or Streamlit secrets."
        )

    response = requests.post(
        API_URL,
        headers={
            "x-goog-api-key": API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "You are a football tactical analyst. "
                                "Analyze only the statistics provided. "
                                "Do not invent numbers or claim that "
                                "correlation proves causation.\n\n"
                                f"Match data:\n{match_data}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 500,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        timeout=(10, 60),
    )

    if not response.ok:
        raise RuntimeError(
            f"Gemini API error {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()
    candidates = data.get("candidates", [])

    if not candidates:
        raise RuntimeError("Gemini returned no analysis.")

    parts = candidates[0].get("content", {}).get("parts", [])
    analysis = "\n".join(
        part["text"] for part in parts if "text" in part
    ).strip()

    if not analysis:
        raise RuntimeError("Gemini returned no text.")

    return analysis


if __name__ == "__main__":
    try:
        result = generate_tactical_analysis(
            "Example test only: Real Madrid had 12 shots and 6 shots "
            "on target. These are sample values, not verified match data."
        )
        print("=== Tactical Analysis Test ===")
        print(result)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        print("Test failed:", error)
