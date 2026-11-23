from pathlib import Path
import json
import os
import subprocess
import sys
import datetime as dt

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from src.settings import get_setting

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
LOGO_URL = "https://a.espncdn.com/i/teamlogos/soccer/500/86.png"

st.set_page_config(
    page_title="Real Madrid | Tactical Analytics",
    page_icon=LOGO_URL,
    layout="wide",
)

st.logo(LOGO_URL, size="large")

st.html(f"<style>{(PROJECT_ROOT / 'assets' / 'dashboard.css').read_text()}</style>")
st.html(
    f"""
    <header class="dashboard-hero">
      <div class="hero-grid"></div>
      <div class="hero-mark">
        <img src="{LOGO_URL}" alt="Real Madrid crest">
        <i></i>
      </div>
      <div class="hero-copy">
        <p class="hero-eyebrow"><span class="live-dot"></span> Real Madrid · Match intelligence</p>
        <h1>Every detail.<br><strong>Every match.</strong></h1>
        <p class="hero-subtitle">The complete match desk — form, tactics, player data and live context.</p>
      </div>
      <div class="hero-orbit"><span>R</span><i></i></div>
    </header>
    """
)

try:
    from src.gemini_api import format_gemini_error, generate_tactical_analysis
except ImportError:
    generate_tactical_analysis = None

    def format_gemini_error(error: Exception) -> str:
        return str(error)


PLAYER_ALIASES = {
    "player": "Player",
    "name": "Player",
    "team": "Team",
    "position": "Position",
    "season": "Season",
    "competition": "Competition",
    "appearances": "Appearances",
    "minutes": "Minutes",
    "goals": "Goals",
    "assists": "Assists",
    "shots": "Shots",
    "shotsontarget": "Shots on Target",
    "xg": "xG",
    "xa": "xA",
    "passescompleted": "Passes Completed",
    "passesattempted": "Passes Attempted",
    "tackles": "Tackles",
    "interceptions": "Interceptions",
    "verificationstatus": "Verification_Status",
}

MATCH_ALIASES = {
    "date": "Date",
    "competition": "Competition",
    "opponent": "Opponent",
    "venue": "Venue",
    "homeaway": "Home/Away",
    "result": "Result",
    "team": "Team",
    "goalsfor": "Goals For",
    "goalsscored": "Goals For",
    "realmadridgoals": "Goals For",
    "goalsagainst": "Goals Against",
    "opponentgoals": "Goals Against",
    "shots": "Shots",
    "shotsontarget": "Shots on Target",
    "xg": "xG For",
    "xgfor": "xG For",
    "xgagainst": "xG Against",
    "possessionpct": "Possession %",
    "possession": "Possession %",
    "verificationstatus": "Verification_Status",
}

PLAYER_METRICS = [
    "Minutes",
    "Goals",
    "Assists",
    "Shots",
    "Shots on Target",
    "xG",
    "xA",
    "Passes Completed",
    "Passes Attempted",
    "Tackles",
    "Interceptions",
]
MATCH_METRICS = [
    "Goals For",
    "Goals Against",
    "Shots",
    "Shots on Target",
    "xG For",
    "xG Against",
    "Possession %",
]
PLOT_COLORS = ["#2f64d8", "#62b6da", "#b6d84a", "#d7b96d"]


def canonical_key(column: object) -> str:
    return "".join(character for character in str(column).casefold() if character.isalnum())


def normalize_columns(frame: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [
        aliases.get(canonical_key(column), str(column).strip())
        for column in result.columns
    ]
    return result


def read_csv(default_path: Path, label: str) -> tuple[pd.DataFrame, str]:
    try:
        return pd.read_csv(default_path), default_path.name
    except FileNotFoundError:
        st.warning(f"{label} file not found at `{default_path}`. Add the CSV to the data folder.")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
        st.error(f"Could not read {label.lower()} CSV `{default_path.name}`: {exc}")
    return pd.DataFrame(), default_path.name


def refresh_match_data() -> tuple[bool, str]:
    collector = PROJECT_ROOT / "src" / "gemini_collector.py"
    if not collector.exists():
        return False, "The data collector script is missing."

    python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)

    try:
        environment = os.environ.copy()
        api_key = get_setting("GEMINI_API_KEY")
        if api_key:
            environment["GEMINI_API_KEY"] = api_key
        result = subprocess.run(
            [str(python), "-m", "src.gemini_collector"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown collector error").strip()
        return False, detail[-600:]
    return True, "Match and player data refreshed."


@st.cache_data(ttl=300)
def fetch_espn_team_schedule(league: str = "esp.1", team_id: str = "86") -> dict:
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/"
        f"{league}/teams/{team_id}/schedule"
    )
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=300)
def fetch_espn_match_summary(league: str, event_id: str) -> dict:
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/soccer/"
        f"{league}/summary?event={event_id}"
    )
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=300)
def fetch_next_real_madrid_fixture(days_ahead: int = 30) -> dict | None:
    today = dt.datetime.now(dt.timezone.utc).date()
    for offset in range(days_ahead + 1):
        date = today + dt.timedelta(days=offset)
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/soccer/"
            f"esp.1/scoreboard?dates={date:%Y%m%d}&limit=100"
        )
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            continue
        for event in payload.get("events", []):
            name = str(event.get("name", ""))
            if "Real Madrid" not in name:
                continue
            for competitor in event.get("competitions", [{}])[0].get("competitors", []):
                team = competitor.get("team", {})
                if team.get("id") == "86":
                    return event
    return None


def get_fixture_teams(event: dict) -> tuple[dict, dict]:
    competition = event.get("competitions", [{}])[0]
    competitors = competition.get("competitors", [])
    real_madrid = next(
        (item for item in competitors if item.get("team", {}).get("id") == "86"),
        competitors[0] if competitors else {},
    )
    opponent = next(
        (item for item in competitors if item is not real_madrid),
        {},
    )
    return real_madrid, opponent


@st.fragment(run_every="30m", key="automatic_match_refresh")
def automatic_match_refresh():
    now = dt.datetime.now(dt.timezone.utc)
    last_auto_refresh = st.session_state.get("last_auto_refresh")
    if (
        last_auto_refresh is not None
        and now - last_auto_refresh < dt.timedelta(minutes=30)
    ):
        return

    refreshed, _ = refresh_match_data()
    st.session_state["last_auto_refresh"] = now
    if refreshed:
        st.rerun()



def prepare_data(
    frame: pd.DataFrame,
    metrics: list[str],
) -> tuple[pd.DataFrame, list[str]]:
    result = frame.copy()
    if result.empty:
        return result, metrics

    if "Team" in result.columns:
        team_names = result["Team"].astype(str).str.strip().str.casefold()
        result = result[team_names.isin({"real madrid", "real madrid cf"})].copy()

    missing = [metric for metric in metrics if metric not in result.columns]
    for metric in metrics:
        if metric in result.columns:
            result[metric] = pd.to_numeric(result[metric], errors="coerce")

    if "Date" in result.columns:
        result["Date"] = pd.to_datetime(result["Date"], errors="coerce")

    return result, missing


def format_total(frame: pd.DataFrame, column: str, decimals: int = 0) -> str:
    if column not in frame.columns or frame[column].notna().sum() == 0:
        return "—"
    return f"{frame[column].sum():,.{decimals}f}"


def format_average(frame: pd.DataFrame, column: str, decimals: int = 2) -> str:
    if column not in frame.columns or frame[column].notna().sum() == 0:
        return "—"
    return f"{frame[column].mean():,.{decimals}f}"


def style_figure(figure, height: int = 330):
    figure.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=30, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#10213a", family="Inter, sans-serif", size=12),
        title=dict(font=dict(size=15, color="#10213a")),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            linecolor="rgba(16,33,58,0.12)",
        ),
        yaxis=dict(
            gridcolor="rgba(16,33,58,0.08)",
            zeroline=False,
            linecolor="rgba(16,33,58,0.12)",
        ),
    )
    return figure


with st.sidebar:
    st.markdown("## Dashboard filters")

raw_players, players_source = read_csv(DATA_DIR / "players.csv", "Player statistics")
raw_matches, matches_source = read_csv(DATA_DIR / "matches.csv", "Match statistics")

players = normalize_columns(raw_players, PLAYER_ALIASES)
matches = normalize_columns(raw_matches, MATCH_ALIASES)
players, missing_player_metrics = prepare_data(players, PLAYER_METRICS)
matches, missing_match_metrics = prepare_data(matches, MATCH_METRICS)

with st.sidebar:
    st.markdown("## Live data")
    if st.button("Refresh match data", icon=":material/refresh:", width="stretch"):
        with st.spinner("Collecting the latest Real Madrid matches and player data..."):
            refreshed, refresh_message = refresh_match_data()
        if refreshed:
            st.success(refresh_message)
            st.session_state["last_manual_refresh"] = dt.datetime.now(dt.timezone.utc)
            st.rerun()
        else:
            st.error(refresh_message)

    latest_refresh = st.session_state.get("last_manual_refresh")
    if latest_refresh is None:
        match_files = [
            DATA_DIR / "matches.csv",
            DATA_DIR / "players.csv",
        ]
        existing_times = [
            dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
            for path in match_files
            if path.exists()
        ]
        latest_refresh = max(existing_times, default=None)
    if latest_refresh is not None:
        st.caption(
            f"Last local update: {latest_refresh.astimezone().strftime('%d %b %Y, %H:%M')}"
        )

automatic_match_refresh()

competitions = set()
for frame in (players, matches):
    if "Competition" in frame.columns:
        competitions.update(frame["Competition"].dropna().astype(str).unique())
competition_options = ["All competitions", *sorted(competitions)]

with st.sidebar:
    selected_competition = st.selectbox("Competition", competition_options)

if selected_competition != "All competitions":
    if "Competition" in players.columns:
        players = players[players["Competition"].astype(str) == selected_competition].copy()
    if "Competition" in matches.columns:
        matches = matches[matches["Competition"].astype(str) == selected_competition].copy()

if "Date" in matches.columns and matches["Date"].notna().any():
    valid_dates = matches["Date"].dropna()
    earliest_date = valid_dates.min().date()
    latest_date = valid_dates.max().date()
    if earliest_date < latest_date:
        with st.sidebar:
            date_range = st.date_input(
                "Match date range",
                value=(earliest_date, latest_date),
                min_value=earliest_date,
                max_value=latest_date,
            )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            matches = matches[
                matches["Date"].dt.date.between(start_date, end_date)
            ].copy()

st.caption(
    f"Match data: **{matches_source}** · Player data: **{players_source}**"
)

st.markdown(
    "<div class='section-kicker'>Match desk</div>",
    unsafe_allow_html=True,
)
st.header("Latest and next")

try:
    live_schedule = fetch_espn_team_schedule()
    schedule_events = live_schedule.get("events", [])
except (requests.RequestException, json.JSONDecodeError, ValueError):
    schedule_events = []

completed_events = [
    event for event in schedule_events
    if event.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed")
]
latest_event = completed_events[0] if completed_events else None
next_event = fetch_next_real_madrid_fixture()

match_columns = st.columns([1.18, 0.82], gap="medium")
with match_columns[0]:
    with st.container(border=True):
        if latest_event:
            madrid, opponent = get_fixture_teams(latest_event)
            score = madrid.get("score", "")
            opponent_score = opponent.get("score", "")
            if isinstance(score, dict):
                score = score.get("displayValue", "")
            if isinstance(opponent_score, dict):
                opponent_score = opponent_score.get("displayValue", "")
            competition = latest_event.get("season", {}).get("displayName", "Match")
            date = pd.to_datetime(latest_event["date"], utc=True)

            st.markdown(
                "<div class='match-status-row'><span class='match-status final'>Full time</span>"
                f"<span>{competition}</span></div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='match-scoreboard'>"
                f"<div><strong>Real Madrid</strong><span>RMA</span></div>"
                f"<div class='score'><b>{score or '—'}</b><i>–</i><b>{opponent_score or '—'}</b></div>"
                f"<div><strong>{opponent.get('team', {}).get('displayName', 'Opponent')}</strong>"
                f"<span>{opponent.get('team', {}).get('abbreviation', 'OPP')}</span></div>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"{date.strftime('%d %B %Y · %H:%M')} UTC"
                + (" · " + str(latest_event.get("competitions", [{}])[0].get("venue", {}).get("fullName", "")))
            )

            try:
                summary = fetch_espn_match_summary(
                    "esp.1",
                    str(latest_event["id"]),
                )
                team_stats = summary.get("boxscore", {}).get("teams", [])
                madrid_stats = next(
                    (team for team in team_stats if team.get("team", {}).get("id") == "86"),
                    team_stats[0] if team_stats else {},
                )
                opponent_stats = next(
                    (team for team in team_stats if team.get("team", {}).get("id") != "86"),
                    team_stats[1] if len(team_stats) > 1 else {},
                )
                selected_stats = ("possessionPct", "totalShots", "shotsOnTarget", "accuratePasses")
                stat_values = {}
                for team, name in ((madrid_stats, "madrid"), (opponent_stats, "opponent")):
                    stat_values[name] = {
                        item["name"]: item["displayValue"]
                        for item in team.get("statistics", [])
                    }

                stat_cols = st.columns(4)
                for index, (name, label) in enumerate(
                    (
                        ("possessionPct", "Possession"),
                        ("totalShots", "Shots"),
                        ("shotsOnTarget", "On target"),
                        ("accuratePasses", "Accurate passes"),
                    )
                ):
                    stat_cols[index].metric(
                        label,
                        stat_values["madrid"].get(name, "—"),
                        delta=(
                            f"vs {stat_values['opponent'].get(name, '—')}"
                        ),
                    )

                timeline, lineups, details = st.tabs(
                    ["Match timeline", "Starting lineups", "Match details"]
                )
                with timeline:
                    goals = [
                        event for event in summary.get("keyEvents", [])
                        if event.get("scoringPlay")
                        or event.get("type", {}).get("type") in {"goal", "red-card", "yellow-card"}
                    ]
                    if goals:
                        for goal in goals[-10:]:
                            minute = goal.get("clock", {}).get("displayValue", "")
                            st.markdown(
                                f"<div class='timeline-event'><span>{minute}</span>"
                                f"<strong>{goal.get('type', {}).get('text', 'Event')}</strong>"
                                f"<p>{goal.get('text') or goal.get('shortText', '')}</p></div>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("No detailed timeline events are available.")
                with lineups:
                    madrid_roster = next(
                        (
                            roster for roster in summary.get("rosters", [])
                            if roster.get("team", {}).get("id") == "86"
                        ),
                        {},
                    )
                    starters = [
                        player for player in madrid_roster.get("roster", [])
                        if player.get("starter")
                    ]
                    if starters:
                        lineup_text = " · ".join(
                            player["athlete"]["displayName"] for player in starters
                        )
                        st.markdown(lineup_text)
                    else:
                        st.caption("Starting lineup is not available.")
                with details:
                    game_info = summary.get("gameInfo", {})
                    venue = game_info.get("venue", {})
                    detail_cols = st.columns(3)
                    detail_cols[0].metric("Venue", venue.get("fullName", "—"))
                    detail_cols[1].metric(
                        "Attendance",
                        f"{game_info.get('attendance', 0):,}"
                        if game_info.get("attendance")
                        else "—",
                    )
                    detail_cols[2].metric(
                        "Season",
                        str(latest_event.get("season", {}).get("year", "—")),
                    )
            except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
                st.caption(f"Full match summary unavailable: {exc}")
        else:
            st.info("No completed Real Madrid match is available.")

with match_columns[1]:
    with st.container(border=True):
        st.markdown("<div class='section-kicker'>Up next</div>", unsafe_allow_html=True)
        if next_event:
            madrid, opponent = get_fixture_teams(next_event)
            date = pd.to_datetime(next_event["date"], utc=True)
            venue = next_event.get("competitions", [{}])[0].get("venue", {})
            st.markdown(
                "<div class='next-match'>"
                f"<span>{next_event.get('season', {}).get('displayName', 'La Liga')}</span>"
                "<h3>Real Madrid <small>vs</small> "
                f"{opponent.get('team', {}).get('displayName', 'Opponent')}</h3>"
                f"<strong>{date.strftime('%d %b · %H:%M')}</strong>"
                f"<p>{venue.get('fullName', 'Venue to be confirmed')}</p>"
                "</div>",
                unsafe_allow_html=True,
            )
            if st.button(
                "Prepare match briefing",
                icon=":material/analytics:",
                width="stretch",
                key="prepare_next_match",
            ):
                if generate_tactical_analysis is None:
                    st.error("Gemini analysis is unavailable.")
                else:
                    next_prompt = (
                        "Prepare a pre-match tactical briefing for this fixture. "
                        "Use only the supplied fixture and current Real Madrid data. "
                        "Clearly separate confirmed facts from tactical hypotheses.\n\n"
                        f"Fixture: {next_event.get('name')}\n"
                        f"Date: {date.strftime('%Y-%m-%d %H:%M UTC')}\n"
                        f"Opponent: {opponent.get('team', {}).get('displayName')}\n"
                        f"Venue: {venue.get('fullName', 'Venue unavailable')}\n\n"
                        "Recent Real Madrid data:\n"
                        f"{matches.head(100).to_csv(index=False)}"
                    )
                    with st.spinner("Building the match briefing..."):
                        try:
                            next_report = generate_tactical_analysis(next_prompt)
                        except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
                            st.error(
                                format_gemini_error(exc),
                                title="Gemini analysis unavailable",
                            )
                        else:
                            st.session_state["next_match_report"] = next_report
                            st.session_state["next_match_report_id"] = str(next_event["id"])

            if (
                st.session_state.get("next_match_report")
                and st.session_state.get("next_match_report_id") == str(next_event["id"])
            ):
                st.markdown("**Tactical briefing**")
                st.markdown(st.session_state["next_match_report"])
        else:
            st.caption("No upcoming fixture found in the next 30 days.")

if missing_match_metrics:
    st.caption(
        "Not provided in match data: " + ", ".join(missing_match_metrics)
    )
if matches.empty:
    st.info("No match rows are available for the selected filters.")
else:
    metric_columns = st.columns(4)
    metric_columns[0].metric("Matches", f"{len(matches):,}")
    metric_columns[1].metric("Goals scored", format_total(matches, "Goals For"))
    metric_columns[2].metric("Goals conceded", format_total(matches, "Goals Against"))
    metric_columns[3].metric("Goals per match", format_average(matches, "Goals For"))

    match_stat_columns = st.columns(5)
    match_stat_columns[0].metric("xG for / match", format_average(matches, "xG For"))
    match_stat_columns[1].metric("xG against / match", format_average(matches, "xG Against"))
    match_stat_columns[2].metric(
        "Possession", f"{format_average(matches, 'Possession %')}%"
        if "Possession %" in matches.columns and matches["Possession %"].notna().any()
        else "—"
    )
    match_stat_columns[3].metric("Total shots", format_total(matches, "Shots"))
    match_stat_columns[4].metric("Shots on target", format_total(matches, "Shots on Target"))

    result_counts = pd.Series(dtype="int64")
    if "Result" in matches.columns:
        result_counts = matches["Result"].astype(str).str.upper().value_counts()
    elif {"Goals For", "Goals Against"}.issubset(matches.columns):
        complete_scores = matches.dropna(subset=["Goals For", "Goals Against"])
        outcomes = complete_scores.apply(
            lambda row: (
                "W" if row["Goals For"] > row["Goals Against"]
                else "D" if row["Goals For"] == row["Goals Against"]
                else "L"
            ),
            axis=1,
        )
        result_counts = outcomes.value_counts()
    form_labels = [
        f"{label} {int(result_counts.get(label, 0))}"
        for label in ("W", "D", "L")
    ]
    st.markdown(
        f'<div class="form-strip"><span class="form-title">RESULTS IN VIEW</span>'
        f'<span class="form-chip win">{form_labels[0]}</span>'
        f'<span class="form-chip draw">{form_labels[1]}</span>'
        f'<span class="form-chip loss">{form_labels[2]}</span></div>',
        unsafe_allow_html=True,
    )

    trend_col, comparison_col = st.columns([1.35, 1])
    with trend_col:
        with st.container(border=True):
            st.subheader("Scoring trend")
            if "Goals For" in matches.columns:
                plot_matches = matches.copy()
                x_axis = "Date" if "Date" in plot_matches.columns else None
                if x_axis is None:
                    plot_matches["Match"] = range(1, len(plot_matches) + 1)
                    x_axis = "Match"
                elif plot_matches[x_axis].isna().all():
                    plot_matches["Match"] = range(1, len(plot_matches) + 1)
                    x_axis = "Match"
                plot_matches = plot_matches.sort_values(x_axis)
                scoring_chart = px.line(
                    plot_matches,
                    x=x_axis,
                    y="Goals For",
                    markers=True,
                    color_discrete_sequence=[PLOT_COLORS[0]],
                    labels={"Goals For": "Goals", "Date": "Match date"},
                )
                scoring_chart.update_traces(line=dict(width=3), marker=dict(size=8))
                st.plotly_chart(
                    style_figure(scoring_chart),
                    width="stretch",
                    config={"displayModeBar": False},
                )
            else:
                st.caption("Add a Goals_For column to see the scoring trend.")
    with comparison_col:
        with st.container(border=True):
            st.subheader("Goals for and against")
            score_columns = [
                column for column in ("Goals For", "Goals Against")
                if column in matches.columns
            ]
            if score_columns:
                opponent_column = "Opponent" if "Opponent" in matches.columns else None
                chart_data = matches.copy()
                if opponent_column is None:
                    chart_data["Match"] = [f"Match {i}" for i in range(1, len(chart_data) + 1)]
                    opponent_column = "Match"
                goal_chart = px.bar(
                    chart_data,
                    x=opponent_column,
                    y=score_columns,
                    barmode="group",
                    color_discrete_sequence=PLOT_COLORS[:2],
                    labels={"value": "Goals", "variable": "Measure"},
                )
                st.plotly_chart(
                    style_figure(goal_chart),
                    width="stretch",
                    config={"displayModeBar": False},
                )
            else:
                st.caption("Add Goals_For and/or Goals_Against to compare scores.")

    xg_columns = [column for column in ("xG For", "xG Against") if column in matches.columns]
    if xg_columns and matches[xg_columns].notna().any().any():
        with st.container(border=True):
            st.subheader("Expected goals")
            xg_data = matches.dropna(subset=xg_columns, how="all").copy()
            x_axis = "Opponent" if "Opponent" in xg_data.columns else None
            if x_axis is None:
                xg_data["Match"] = [f"Match {i}" for i in range(1, len(xg_data) + 1)]
                x_axis = "Match"
            xg_chart = px.bar(
                xg_data,
                x=x_axis,
                y=xg_columns,
                barmode="group",
                color_discrete_sequence=PLOT_COLORS[:2],
                labels={"value": "Expected goals", "variable": "Measure"},
            )
            st.plotly_chart(
                style_figure(xg_chart, 300),
                width="stretch",
                config={"displayModeBar": False},
            )

    with st.expander("Match data", expanded=False):
        st.dataframe(
            matches,
            hide_index=True,
            width="stretch",
            alt="Filtered Real Madrid match data",
            column_config={
                "Source_URL": st.column_config.LinkColumn(
                    "Match source",
                    display_text="Open ESPN match data",
                )
            },
        )
        st.download_button(
            "Download match data",
            data=matches.to_csv(index=False).encode("utf-8"),
            file_name="real_madrid_matches.csv",
            mime="text/csv",
        )

st.header("Player analytics")
if missing_player_metrics:
    st.caption(
        "Not provided in player data: " + ", ".join(missing_player_metrics)
    )
if players.empty:
    st.info("No player rows are available for the selected filters.")
elif "Player" not in players.columns:
    st.error("The player CSV must include a Player column.")
else:
    player_view = players.copy()
    if "Position" in player_view.columns:
        position_options = sorted(player_view["Position"].dropna().astype(str).unique())
        if position_options:
            selected_positions = st.multiselect(
                "Positions",
                position_options,
                default=position_options,
            )
            player_view = player_view[
                player_view["Position"].astype(str).isin(selected_positions)
            ].copy()

    if player_view.empty:
        st.info("No players match the selected positions.")
    else:
        player_metrics = st.columns(4)
        player_metrics[0].metric("Players", f"{player_view['Player'].nunique():,}")
        player_metrics[1].metric("Goals", format_total(player_view, "Goals"))
        player_metrics[2].metric("Assists", format_total(player_view, "Assists"))
        if (
            {"Shots", "Shots on Target"}.issubset(player_view.columns)
            and player_view["Shots"].sum(min_count=1) > 0
        ):
            accuracy = (
                100 * player_view["Shots on Target"].sum()
                / player_view["Shots"].sum()
            )
            player_metrics[3].metric("Shot accuracy", f"{accuracy:.1f}%")
        else:
            player_metrics[3].metric("Shot accuracy", "—")

        available_rankings = [
            metric for metric in ("Goals", "Assists", "xG", "xA")
            if metric in player_view.columns and player_view[metric].notna().any()
        ]
        if available_rankings:
            ranking_metric = st.selectbox("Rank players by", available_rankings)
            ranking = (
                player_view.groupby("Player", as_index=False)[ranking_metric]
                .sum(min_count=1)
                .dropna(subset=[ranking_metric])
                .sort_values(ranking_metric, ascending=True)
            )
            with st.container(border=True):
                st.subheader(f"Player ranking · {ranking_metric}")
                ranking_chart = px.bar(
                    ranking,
                    x=ranking_metric,
                    y="Player",
                    orientation="h",
                    color_discrete_sequence=[PLOT_COLORS[0]],
                    labels={ranking_metric: ranking_metric, "Player": ""},
                )
                st.plotly_chart(
                    style_figure(ranking_chart, max(300, 38 * len(ranking))),
                    width="stretch",
                    config={"displayModeBar": False},
                )

        if (
            {"Goals", "xG"}.issubset(player_view.columns)
            and player_view[["Goals", "xG"]].notna().any().any()
        ):
            with st.container(border=True):
                st.subheader("Goals compared with expected goals")
                comparison = (
                    player_view.groupby("Player", as_index=False)[["Goals", "xG"]]
                    .sum(min_count=1)
                )
                comparison_chart = px.bar(
                    comparison,
                    x="Player",
                    y=["Goals", "xG"],
                    barmode="group",
                    color_discrete_sequence=PLOT_COLORS[:2],
                    labels={"value": "Season total", "variable": "Metric"},
                )
                st.plotly_chart(
                    style_figure(comparison_chart),
                    width="stretch",
                    config={"displayModeBar": False},
                )

        with st.expander("Player statistics", expanded=False):
            st.dataframe(
                player_view,
                hide_index=True,
                width="stretch",
                alt="Filtered Real Madrid player statistics",
            )
            st.download_button(
                "Download player data",
                data=player_view.to_csv(index=False).encode("utf-8"),
                file_name="real_madrid_players.csv",
                mime="text/csv",
            )

st.header("Gemini tactical analyst")
st.caption(
    "Ask for an interpretation of the selected data. The analyst does not verify or add statistics."
)
analysis_type = st.radio(
    "Dataset to analyze",
    ["Team analysis", "Player analysis"],
    horizontal=True,
)
analysis_question = st.text_area(
    "What should Gemini investigate?",
    "Identify the main statistical trends, explain strengths and weaknesses, "
    "compare available metrics, and state the limitations of the dataset. "
    "Use only the supplied data.",
)

if st.button(
    "Generate tactical analysis",
    type="primary",
):
    analysis_data = matches if analysis_type == "Team analysis" else players
    if generate_tactical_analysis is None:
        st.error("Gemini analysis is unavailable because src/gemini_api.py could not be imported.")
    elif not analysis_question.strip():
        st.warning("Enter a question for the tactical analysis.")
    elif analysis_data.empty:
        st.warning("No data is available for this analysis. Check the selected filters or upload a CSV.")
    else:
        prompt = f"""
You are a careful Real Madrid football data analyst.

Analyze only the supplied dataset. Do not invent statistics, matches, players,
injuries, formations, or events. Explain uncertainty and missing columns.
Distinguish measured facts from tactical hypotheses. Do not claim correlation proves causation.

Analysis requested:
{analysis_question}

Dataset:
{analysis_data.head(150).to_csv(index=False)}

Rows available: {len(analysis_data)}
"""
        with st.spinner("Analyzing the supplied data..."):
            try:
                report = generate_tactical_analysis(prompt)
            except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
                st.error(
                    format_gemini_error(exc),
                    title="Gemini analysis unavailable",
                )
            else:
                st.markdown(report)
                st.download_button(
                    "Download tactical report",
                    data=report,
                    file_name="real_madrid_tactical_report.txt",
                    mime="text/plain",
                )

st.markdown(
    '<footer class="dashboard-footer">REAL MADRID TACTICAL ANALYTICS'
    '<span>·</span> Results depend on the accuracy and verification of the supplied data.'
    '<br><span class="footer-credit">Code by Walid Arrich</span></footer>',
    unsafe_allow_html=True,
)
