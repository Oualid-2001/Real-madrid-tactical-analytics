# Real Madrid Tactical Analytics

A light-themed Streamlit dashboard for Real Madrid match intelligence, with historical team and player analytics, a latest-match center, upcoming fixture details, and optional Gemini tactical briefings.

The interface uses a Real Madrid crest image served by ESPN. The app does not bundle the crest file.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The dashboard loads `data/matches.csv` and `data/players.csv` automatically. It fetches the latest completed match, match summary, and upcoming La Liga fixture from ESPN. Historical match and player tables are local CSV files; source links and verification status are retained in the data. Missing metrics are displayed as unavailable rather than generated. To use different data, replace the CSVs with files that follow the format below.

Use **Refresh match data** in the sidebar to refresh the CSV data using the Gemini collector. This requires a Gemini API key. The dashboard also checks for updates periodically while it is open. The latest-match summary and upcoming La Liga fixture are fetched from ESPN. Gemini can prepare a pre-match briefing or analyze the selected CSV data.

## CSV data

The app recognizes common header variations, including underscores and spaces. Match data can include `Date`, `Competition`, `Opponent`, `Goals_For`, `Goals_Against`, `xG_For`, `xG_Against`, `Shots`, `Shots_On_Target`, and `Possession_Pct`. Player data can include `Player`, `Position`, `Appearances`, `Minutes`, `Goals`, `Assists`, `Shots`, `Shots_On_Target`, `xG`, and `xA`. Missing metrics are omitted from charts and shown as unavailable rather than generated.

## Gemini API setup

The Gemini API key must stay private; do not commit `.env` or Streamlit secrets to GitHub.

- **Local:** copy `.env.example` to `.env` and set `GEMINI_API_KEY`.
- **Streamlit Community Cloud:** open the app's **Settings → Secrets** and add:

  ```toml
  GEMINI_API_KEY = "your-gemini-api-key"
  GEMINI_MODEL = "gemini-2.5-flash"
  ```

The app's analysis and data refresh features read the key from either location. `.streamlit/secrets.toml` is ignored by Git. A safe template is available in `.streamlit/secrets.toml.example`. The analyst uses supplied data and does not independently verify its source.

## Data notes

The sample CSVs include source URLs and verification labels. Check source links before relying on statistics. The dashboard requests live fixture and summary data from ESPN when it runs; those endpoints may change or be unavailable.
