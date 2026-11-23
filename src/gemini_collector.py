"""Collect candidate Real Madrid statistics using Gemini."""

import json
import re
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src.settings import get_setting

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / ".env")

API_KEY = get_setting("GEMINI_API_KEY")
MODEL = get_setting("GEMINI_MODEL", "gemini-2.5-flash")
API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent"
)

MATCH_COLUMNS = [
    "Date", "Competition", "Opponent", "Venue",
    "Real_Madrid_Goals", "Opponent_Goals", "Result",
    "Possession_Pct", "Shots", "Shots_On_Target",
    "xG", "xG_Against", "Source_URL", "Verification_Status",
]

PLAYER_COLUMNS = [
    "Player", "Position", "Appearances", "Minutes",
    "Goals", "Assists", "Shots", "Shots_On_Target",
    "xG", "xA", "Source_URL", "Verification_Status",
]


def ask_gemini(prompt):
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
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 6000,
            },
        },
        timeout=(15, 120),
    )

    if not response.ok:
        raise RuntimeError(
            f"Gemini HTTP {response.status_code}: "
            f"{response.text[:600]}"
        )

    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates.")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(
        part["text"] for part in parts if "text" in part
    ).strip()

    if not text:
        raise RuntimeError("Gemini returned no text.")

    # Extract source URLs returned by Google Search grounding.
    sources = []
    metadata = candidates[0].get("groundingMetadata", {})
    for chunk in metadata.get("groundingChunks", []):
        web = chunk.get("web", {})
        url = web.get("uri")
        if url and url not in sources:
            sources.append(url)

    # Accept JSON surrounded by Markdown fences, if present.
    text = re.sub(r"^\s*```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Gemini did not return valid JSON. No CSV was changed."
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError("Expected a JSON object. No CSV was changed.")

    return result, sources


def collect(dataset, columns, prompt):
    print(f"\nRequesting {dataset} data from Gemini...")
    result, sources = ask_gemini(prompt)
    records = result.get(dataset, [])

    if not isinstance(records, list) or not records:
        print(f"No usable {dataset} records. Existing CSV preserved.")
        return

    cleaned = []
    for record in records:
        if not isinstance(record, dict):
            continue

        row = {column: record.get(column) for column in columns}
        row["Source_URL"] = row.get("Source_URL") or (
            sources[0] if sources else ""
        )
        row["Verification_Status"] = (
            "Source available - verify figures"
            if row["Source_URL"]
            else "Unverified - no source URL"
        )
        cleaned.append(row)

    if not cleaned:
        print(f"No valid {dataset} rows. Existing CSV preserved.")
        return

    output = DATA_DIR / f"{dataset}.csv"
    pd.DataFrame(cleaned, columns=columns).to_csv(
        output, index=False
    )
    print(f"Saved {len(cleaned)} candidate rows to {output}")
    print(f"Grounding URLs found: {len(sources)}")
    print("IMPORTANT: Verify the figures before using them.")


def main():
    print("Real Madrid Tactical Analytics — Gemini collector")
    print(f"Model: {MODEL}")

    collect(
        "matches",
        MATCH_COLUMNS,
        """
Research Real Madrid men's first-team competitive matches from the
2026-27 season up to today, using Google Search. Return only matches
you can identify from reliable sources. Do not invent statistics.
If a field such as xG, possession, or shots is unavailable, use null.
Return a JSON object with a "matches" array. Each item must contain:
Date, Competition, Opponent, Venue, Real_Madrid_Goals,
Opponent_Goals, Result, Possession_Pct, Shots, Shots_On_Target,
xG, Source_URL. Dates must be YYYY-MM-DD. Result must be W, D, or L.
Include xG_Against when opponent expected goals are available.
Source_URL should be a URL supporting that specific record when known.
Do not include friendlies. Do not claim unavailable data is verified.
""",
    )

    collect(
        "players",
        PLAYER_COLUMNS,
        """
Research Real Madrid men's first-team player statistics for the
2026-27 season up to today, using Google Search. Use reliable sources
and clearly distinguish season totals from per-match statistics.
Do not invent numbers. Use null when a field cannot be verified.
Return a JSON object with a "players" array. Each item must contain:
Player, Position, Appearances, Minutes, Goals, Assists, Shots,
Shots_On_Target, xG, xA, Source_URL. Use season totals where available.
Source_URL should support the specific record when known.
Do not treat missing statistics as zero.
""",
    )

    print("\nCollection finished. Review the CSVs and verify every row.")


if __name__ == "__main__":
    try:
        main()
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"\nCollection failed: {exc}")
