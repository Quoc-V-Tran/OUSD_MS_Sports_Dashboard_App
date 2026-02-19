"""
OUSD OAL Middle School Sports Dashboard — Production
Features: Batch API, Quota Retry, Full Normalization, and Professional UI.
"""

import json
import re
import time
import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Config & Normalization Helpers
# ---------------------------------------------------------------------------
FOLDER_ID = "18B2JDMzmEqmeAk8T2vwswX5T-koYUMQV"
SERVICE_ACCOUNT_FILE = "service_account.json"
# For Streamlit Cloud: set gcp_service_account in Secrets to the service account dict (no file needed)
HEADER_SEARCH_MAX_ROWS = 15
MAX_ROWS_PER_SHEET = 800
DELAY_BETWEEN_SPREADSHEETS = 1.2

TARGET_HEADERS = ["STUDENT ID", "Last Name", "First Name", "Gendar", "Year", "GPA", "PHYSICAL"]

HEADER_ALIASES = {
    "STUDENT ID": ["STUDENT ID", "Student ID", "Student ID #", "ID"],
    "Last Name": ["Last Name", "Last name", "LastName", "Lname"],
    "First Name": ["First Name", "First name", "FirstName", "Fname"],
    "Gendar": ["Gendar", "Gender"],
    "Year": ["Year", "Grade", "Grade Year"],
    "GPA": ["GPA", "Gpa"],
    "PHYSICAL": ["PHYSICAL", "Physical", "Physical Date", "Physical Clearance"],
}

def _strip_tab_prefix(s: str) -> str:
    """Remove leading (M) etc. so tab names like '(M) FLAG FOOTBALL - BOYS YELLOW JV' parse correctly. Keeps (F)/(W)/(S) for season."""
    s = re.sub(r"^\s*\(M\)\s*", "", s, flags=re.IGNORECASE)
    return s.strip()

def _core_sport_string(tab_name: str) -> str:
    if not tab_name: return ""
    s = str(tab_name).strip().upper()
    s = _strip_tab_prefix(s)
    s = re.sub(r"^\s*\([FWS]\)\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*\((?:FALL|WINTER|SPRING)\)\s*", "", s, flags=re.IGNORECASE)
    # Strip trailing gender so core = level + sport + team only
    s = re.sub(r"\s*[-–]\s*GIRLS?\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–]\s*BOYS?\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–]\s*G\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–]\s*B\s*$", "", s, flags=re.IGNORECASE)
    level_team_suffixes = [
        r"\s*[-–]\s*VAR\s*$", r"\s*[-–]\s*VARSITY\s*$", r"\s*[-–]\s*JV\s*$",
        r"\s*[-–]\s*V\s*$", r"\s*[-–]\s*JUNIOR\s+VARSITY\s*$",
        r"\s*[-–]\s*RED\s*$", r"\s*[-–]\s*BLUE\s*$", r"\s*[-–]\s*WHITE\s*$",
        r"\s*[-–]\s*GOLD\s*$", r"\s*[-–]\s*BLACK\s*$", r"\s*[-–]\s*ORANGE\s*$",
        r"\s*[-–]\s*TEAM\s*\d+\s*$", r"\s*[-–]\s*#?\s*\d+\s*$",
        r"\s*\(\s*V\s*\)\s*$", r"\s*VAR\s*$", r"\s*VARSITY\s*$", r"\s*JV\s*$",
        r"\s*#\s*\d+\s*$", r"\s+\d+\s*$",
    ]
    for _ in range(5):
        changed = False
        for pat in level_team_suffixes:
            next_s = re.sub(pat, "", s, flags=re.IGNORECASE)
            if next_s != s: s = next_s.strip(); changed = True
        if not changed: break
    return s.strip()

# Order matters: more specific first. Soccer vs Futsal: "FUTSAL SOCCER" → Futsal; "SOCCER" only → Soccer.
SPORT_KEYWORDS_ORDERED = [
    ("FLAG FOOTBALL", "Flag Football"), ("CROSS COUNTRY", "Cross Country"),
    ("TRACK", "Track & Field"), ("ULTIMATE FRISBEE", "Ultimate Frisbee"),
    ("BASKETBALL", "Basketball"), ("FUTSAL", "Futsal"), ("SOCCER", "Soccer"),
    ("VOLLEYBALL", "Volleyball"), ("CHEER", "Cheerleading"), ("BASEBALL", "Baseball"),
    ("SOFTBALL", "Softball"), ("WRESTLING", "Wrestling"), ("LACROSSE", "Lacrosse")
]

def normalize_sport_name(tab_name: str) -> str:
    """Consolidated Student Roster and all charts use this. Futsal vs Soccer: tab with 'Futsal' → Futsal, else Soccer."""
    core = _core_sport_string(tab_name)
    if not core: return "Other"
    # Explicit: "FUTSAL SOCCER" or any tab containing FUTSAL → Futsal (different sport from Soccer).
    if "FUTSAL" in core:
        return "Futsal"
    for keyword, clean_name in SPORT_KEYWORDS_ORDERED:
        if keyword in core: return clean_name
    return "Other"

def extract_season(tab_name: str) -> str:
    s = str(tab_name).strip().upper()
    s = _strip_tab_prefix(s)
    if re.match(r"^\s*\(F\)", s): return "Fall"
    if re.match(r"^\s*\(W\)", s): return "Winter"
    if re.match(r"^\s*\(S\)", s): return "Spring"
    return "Other"

def normalize_gender(value) -> str:
    s = str(value).strip().upper()
    if s in ("M", "MALE", "BOY", "BOYS"): return "Boys"
    if s in ("F", "FEMALE", "GIRL", "GIRLS"): return "Girls"
    return "Other"

def extract_level(tab_name: str) -> str:
    name = str(tab_name).upper()
    if "6TH" in name: return "6th Grade"
    if "JV" in name or "JUNIOR VARSITY" in name: return "JV"
    return "Varsity"

# Team = color or number in tab name after stripping season, level, gender (e.g. Red, Blue, Yellow, 1, 2).
TEAM_COLORS = ["RED", "BLUE", "WHITE", "GOLD", "BLACK", "ORANGE", "GREEN", "SILVER", "YELLOW", "MAROON", "NAVY", "PURPLE"]

def extract_team(tab_name: str) -> str:
    """After stripping season, gender, and level, last token = team if color or number. Else "—"."""
    if not tab_name: return "—"
    s = str(tab_name).strip().upper()
    s = _strip_tab_prefix(s)
    s = re.sub(r"^\s*\([FWS]\)\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–]\s*GIRLS?\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–]\s*BOYS?\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–]\s*G\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-–]\s*B\s*$", "", s, flags=re.IGNORECASE)
    # Strip level from end so "FLAG FOOTBALL YELLOW JV" → last token = YELLOW not JV
    for level_pat in [r"\s+JV\s*$", r"\s+VARSITY\s*$", r"\s+VAR\s*$", r"\s+V\s*$", r"\s+6TH\s*$", r"\s+JUNIOR\s+VARSITY\s*$"]:
        s = re.sub(level_pat, "", s, flags=re.IGNORECASE).strip()
    tokens = re.split(r"\s+|\s*[-–]\s*", s)
    tokens = [t for t in tokens if t]
    if not tokens: return "—"
    last = tokens[-1]
    if last in TEAM_COLORS: return last.title()
    if last.isdigit(): return last
    digits = re.sub(r"\D", "", last)
    if digits and re.match(r"^(?:TEAM\s*)?#?\d+$", last.replace(" ", "")): return digits
    return "—"

def display_school_name(school: str) -> str:
    s = str(school).strip()
    s = re.sub(r"\s+Official\s+Sports\s+Roster\s+['\u2019]?\d{2}-\d{2}\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*(Official|Sports|Roster|['’]\d{2}-\d{2})\s*", " ", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()

def physical_status(value) -> str:
    """YES = physical complete (yes, approved, cleared, etc.). Otherwise NO."""
    if value is None or (isinstance(value, float) and pd.isna(value)): return "NO"
    s = str(value).strip().upper()
    if not s: return "NO"
    if s in ("YES", "Y", "APPROVED", "APPROVE", "CLEARED", "CLEAR", "COMPLETE", "DONE", "OK"): return "YES"
    if s.startswith("APPROVED") or s.startswith("YES"): return "YES"
    return "NO"

# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

def normalize_val(s):
    if s is None or (isinstance(s, float) and pd.isna(s)): return ""
    return str(s).strip()

def find_header_row(rows):
    for i, row in enumerate(rows[:HEADER_SEARCH_MAX_ROWS]):
        if not row: continue
        for cell in row:
            if normalize_val(cell).upper() == "STUDENT ID": return i
    return None

def map_header_to_target(header_row):
    result = {}
    for target in TARGET_HEADERS:
        aliases = HEADER_ALIASES.get(target, [target])
        for col_idx, cell in enumerate(header_row):
            norm = normalize_val(cell).upper().replace(" ", "")
            for alias in aliases:
                if norm == normalize_val(alias).upper().replace(" ", ""):
                    result[target] = col_idx; break
    return result

def get_cell(row, col_idx, default=""):
    if col_idx is None or col_idx >= len(row): return default
    val = row[col_idx]
    return str(val).strip() if val and not (isinstance(val, float) and pd.isna(val)) else default

def parse_sheet_values(all_values, school_name: str, tab_name: str):
    if not all_values: return []
    h_idx = find_header_row(all_values)
    if h_idx is None: return []
    col_map = map_header_to_target(all_values[h_idx])
    records = []
    for row in all_values[h_idx + 1 :]:
        sid = get_cell(row, col_map.get("STUDENT ID"))
        fname = get_cell(row, col_map.get("First Name"))
        lname = get_cell(row, col_map.get("Last Name"))
        if sid.isdigit() and len(sid) >= 4 and fname and lname:
            g_raw = get_cell(row, col_map.get("Gendar"))
            records.append({
                "School": school_name, "Sport": normalize_sport_name(tab_name),
                "Level": extract_level(tab_name), "Season": extract_season(tab_name),
                "Team": extract_team(tab_name),
                "STUDENT ID": sid, "Last Name": lname, "First Name": fname,
                "Gender": normalize_gender(g_raw), "GPA": get_cell(row, col_map.get("GPA")),
                "PHYSICAL": get_cell(row, col_map.get("PHYSICAL"))
            })
    return records

def _parse_json_with_private_key_newlines(s: str):
    """Parse JSON when 'private_key' value contains literal newlines (invalid in strict JSON)."""
    key = '"private_key"'
    i = s.find(key)
    if i == -1:
        raise json.JSONDecodeError("No 'private_key' key found", s, 0)
    i = s.find('"', i + len(key) + 1)  # skip to value opening quote
    if i == -1:
        raise json.JSONDecodeError("Malformed private_key", s, 0)
    start = i + 1  # start of value content
    end = start
    while end < len(s):
        if s[end] == "\\" and end + 1 < len(s):
            end += 2
            continue
        if s[end] == '"':
            break
        end += 1
    value = s[start:end]
    fixed = value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    new_s = s[:start] + fixed + s[end:]
    return json.loads(new_s)

def _get_creds():
    """Use Streamlit secrets if set (deploy), else local service_account.json (local run)."""
    scopes = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]

    # 1) Try Streamlit Secrets (Cloud deploy)
    if hasattr(st, "secrets") and st.secrets:
        raw = None
        for key in ("gcp_service_account", "GCP_SERVICE_ACCOUNT"):
            try:
                raw = st.secrets.get(key)
                if raw is not None:
                    break
            except Exception:
                continue
        if raw is not None:
            try:
                if isinstance(raw, str):
                    try:
                        info = json.loads(raw)
                    except json.JSONDecodeError as je:
                        if "control character" in str(je).lower() or "line" in str(je).lower():
                            info = _parse_json_with_private_key_newlines(raw)
                        else:
                            raise
                else:
                    info = json.loads(json.dumps(raw))  # normalize dict-like to plain dict
                return Credentials.from_service_account_info(info, scopes=scopes)
            except Exception as e:
                raise RuntimeError(
                    f"Secrets key 'gcp_service_account' is set but invalid: {e}. "
                    "Check that the value is valid JSON or TOML with type, project_id, private_key_id, private_key, client_email."
                ) from e
        # Secrets exist but key missing — likely Cloud with wrong key name
        try:
            keys = list(st.secrets.keys()) if hasattr(st.secrets, "keys") else []
        except Exception:
            keys = []
        raise FileNotFoundError(
            "No credentials found. In Streamlit Cloud → Settings → Secrets, add a key named exactly: gcp_service_account. "
            f"Current secret keys: {keys if keys else '(none)'}. "
            "Value: paste your full service_account.json content as JSON, or use a [gcp_service_account] section with type, project_id, private_key, client_email, etc."
        )

    # 2) Local: use file
    try:
        return Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    except FileNotFoundError:
        raise FileNotFoundError(
            "No credentials found. Add service_account.json locally or set gcp_service_account in Streamlit Secrets (Settings → Secrets)."
        )

@st.cache_data(ttl=600)
def deep_scan(folder_id: str):
    creds = _get_creds()
    drive = build("drive", "v3", credentials=creds); sheets = build("sheets", "v4", credentials=creds)
    response = drive.files().list(q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false", fields="files(id, name)").execute()
    files = [(f["id"], f["name"]) for f in response.get("files", [])]
    all_records = []
    for i, (f_id, f_name) in enumerate(files):
        if i > 0: time.sleep(DELAY_BETWEEN_SPREADSHEETS)
        try:
            meta_resp = sheets.spreadsheets().get(spreadsheetId=f_id, fields="sheets(properties(title,gridProperties(rowCount,columnCount)))").execute()
            meta = [{"title": s["properties"]["title"], "rows": min(s["properties"]["gridProperties"].get("rowCount", 1000), MAX_ROWS_PER_SHEET), "cols": s["properties"]["gridProperties"].get("columnCount", 26)} for s in meta_resp.get("sheets", [])]
            
            # FIXED LINE: Replacement moved out of f-string
            ranges = []
            for m in meta:
                safe_title = m['title'].replace("'", "''")
                ranges.append(f"'{safe_title}'!A1:Z{m['rows']}")
            
            grids_resp = sheets.spreadsheets().values().batchGet(spreadsheetId=f_id, ranges=ranges, valueRenderOption="FORMATTED_VALUE").execute()
            for m, grid in zip(meta, grids_resp.get("valueRanges", [])):
                all_records.extend(parse_sheet_values(grid.get("values", []), f_name, m["title"]))
        except: continue
    if not all_records:
        return pd.DataFrame(columns=["School", "Sport", "Level", "Season", "Team", "STUDENT ID", "Last Name", "First Name", "Gender", "GPA", "PHYSICAL"])
    return pd.DataFrame(all_records)

# ---------------------------------------------------------------------------
# UI Execution
# ---------------------------------------------------------------------------
st.set_page_config(page_title="OAL Sports Dashboard", layout="wide", page_icon="📊")

st.markdown("""
<style>
/* Summary KPI panels: readable dark text on light background */
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] { color: #1f1f1f !important; }
div[data-testid="stMetric"] {
    background-color: #f0f4f8 !important;
    padding: 1rem 1.25rem !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important;
    border: 1px solid #e0e6ed !important;
}
div[data-testid="stMetric"] label { color: #374151 !important; }
</style>
""", unsafe_allow_html=True)
st.title("🏆 OUSD OAL Middle School Sports Data Center")
st.caption("L and Q Company | Authorized Data Portal")

if "roster_df" not in st.session_state: st.session_state["roster_df"] = None

with st.sidebar:
    st.header("Actions")
    if st.button("🚀 Run Deep Scan", type="primary", use_container_width=True):
        try:
            with st.spinner("Processing Roster Data..."):
                df = deep_scan(FOLDER_ID)
            st.session_state["roster_df"] = df[~((df["First Name"].str.upper() == "LAMONT") & (df["Last Name"].str.upper() == "ROBINSON"))].copy()
        except FileNotFoundError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Scan failed: {e}")

    if st.button("🔄 Clear cache & rescan next", use_container_width=True, help="Clear cached roster so next Run Deep Scan re-parses (e.g. Futsal vs Soccer). Then click Run Deep Scan again."):
        deep_scan.clear()
        st.session_state["roster_df"] = None
        st.success("Cache cleared. Click Run Deep Scan to reload.")

    if st.session_state["roster_df"] is not None:
        st.divider()
        st.header("Global Filters")
        raw_df = st.session_state["roster_df"]
        f_school = st.multiselect("School Site", options=sorted(raw_df["School"].unique()), default=raw_df["School"].unique())
        f_level = st.multiselect("Level", options=sorted(raw_df["Level"].unique()), default=raw_df["Level"].unique())
        f_season = st.multiselect("Season", options=["Fall", "Winter", "Spring"], default=["Fall", "Winter", "Spring"])
        f_gender = st.radio("Gender Focus", options=["All", "Boys", "Girls"])
        team_opts = sorted(raw_df["Team"].dropna().unique().tolist()) if "Team" in raw_df.columns else []
        # Include "—" (no sub-team) so "all selected" shows full roster; only filter when user picks a subset
        f_team = st.multiselect("Team (color/number)", options=team_opts, default=team_opts if team_opts else [], help="Filter by sub-team: Red, Blue, Yellow, 1, 2, etc. Leave all selected for full roster.") if team_opts else []

df = st.session_state["roster_df"]
if df is not None:
    mask = (df["School"].isin(f_school)) & (df["Level"].isin(f_level)) & (df["Season"].isin(f_season))
    if f_gender != "All": mask = mask & (df["Gender"] == f_gender)
    if "Team" in df.columns and isinstance(f_team, list) and len(f_team) > 0: mask = mask & (df["Team"].isin(f_team))
    
    display_df = df[mask].copy()
    display_df["GPA"] = pd.to_numeric(display_df["GPA"], errors="coerce")
    df_with_gpa = display_df[display_df["GPA"].notna()]

    # Summary KPI panels (styled for contrast: dark text on light background)
    st.subheader("📈 Summary")
    avg_gpa = df_with_gpa["GPA"].mean() if len(df_with_gpa) > 0 else 0
    physicals_yes = (display_df["PHYSICAL"].apply(physical_status) == "YES").sum()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Athletes", f"{len(display_df):,}")
    k2.metric("Avg District GPA", f"{avg_gpa:.2f}" if len(df_with_gpa) > 0 else "—")
    k3.metric("Physicals Cleared", f"{physicals_yes:,}")
    k4.metric("Active Sports", display_df["Sport"].nunique())

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 DASHBOARD", "📋 DETAILED DATA", "🔍 SITE SPOT-CHECK", "🚩 FLAGS", "💰 Budget Request"])

    with tab1:
        st.subheader("Participation & Academic Trends")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Participation by Sport**")
            s_counts = display_df["Sport"].value_counts().reset_index()
            st.bar_chart(s_counts, x="Sport", y="count", color="#ffc300")
            
            st.markdown("**Participation by Gender**")
            g_counts = display_df["Gender"].value_counts().reset_index()
            st.bar_chart(g_counts, x="Gender", y="count", color="#003566")

        with c2:
            st.markdown("**GPA average by School**")
            gpa_s = df_with_gpa.groupby("School")["GPA"].mean().sort_values(ascending=False).reset_index()
            gpa_s["School"] = gpa_s["School"].apply(display_school_name)
            st.bar_chart(gpa_s, x="School", y="GPA", color="#003566")

            st.markdown("**Medical Eligibility (Physicals)**")
            p_counts = display_df["PHYSICAL"].apply(physical_status).value_counts().reset_index()
            st.bar_chart(p_counts, x="PHYSICAL", y="count", color="#28a745")

    with tab2:
        st.subheader("Consolidated Student Roster")
        roster_disp = display_df.copy()
        roster_disp["School"] = roster_disp["School"].apply(display_school_name)
        if "Team" in roster_disp.columns:
            roster_disp = roster_disp.rename(columns={"Team": "Team Type"})
            # Order columns so Team Type appears after Sport/Level (color or number for multiple teams per school)
            cols = [c for c in ["School", "Sport", "Level", "Team Type", "Season", "STUDENT ID", "Last Name", "First Name", "Gender", "GPA", "PHYSICAL"] if c in roster_disp.columns]
            roster_disp = roster_disp[[c for c in cols] + [c for c in roster_disp.columns if c not in cols]]
        st.dataframe(roster_disp, use_container_width=True, height=500)
        st.download_button("📥 Export CSV", roster_disp.to_csv(index=False), "roster.csv", "text/csv")

    with tab3:
        st.subheader("School-Level Deep Dive")
        spot_df = df.copy()
        spot_df["GPA"] = pd.to_numeric(spot_df["GPA"], errors="coerce")
        spot_df["School_Disp"] = spot_df["School"].apply(display_school_name)
        
        school_sel = st.selectbox("Focus on School", options=["All schools"] + sorted(spot_df["School_Disp"].unique().tolist()))
        
        view_df = spot_df if school_sel == "All schools" else spot_df[spot_df["School_Disp"] == school_sel]
        
        st.markdown(f"**Performance Breakdown: {school_sel}**")
        stats = view_df.groupby(["Level", "Sport"]).agg(Athletes=("STUDENT ID", "count"), Avg_GPA=("GPA", "mean")).reset_index()
        st.dataframe(stats.style.format({"Avg_GPA": "{:.3f}"}), use_container_width=True)

    with tab4:
        st.subheader("🚩 Data quality flags")
        st.caption("School/sport combinations with missing or off data—e.g. athletes with no gender (shown as Other in Participation by Gender). Use this to follow up with coaches.")

        # Summary: flag when missing data is >50% of athletes in each school/sport/level
        flag_summary_df = display_df.copy()
        flag_summary_df["School_disp"] = flag_summary_df["School"].apply(display_school_name)
        flag_summary_df["_other_gender"] = (flag_summary_df["Gender"] == "Other").astype(int)
        flag_summary_df["_missing_gpa"] = flag_summary_df["GPA"].isna().astype(int)
        flag_summary_df["_incomplete_physical"] = (flag_summary_df["PHYSICAL"].apply(physical_status) != "YES").astype(int)
        summary_grp = (
            flag_summary_df.groupby(["School_disp", "Sport", "Level"], as_index=False)
            .agg(
                Total=("STUDENT ID", "count"),
                Missing_gender_n=("_other_gender", "sum"),
                Missing_GPA_n=("_missing_gpa", "sum"),
                Incomplete_physical_n=("_incomplete_physical", "sum"),
            )
        )
        FLAG_EMOJI = "🚩"
        def _pct_cell(n, total, flag_emoji):
            pct = int(round(n / total * 100, 0)) if total else 0
            # Pad so column sort is numeric: "  0%", " 25%", "100%" then append 🚩 when >50%
            base = f"{pct:>3}%"
            return f"{base} {flag_emoji}" if total and (n / total > 0.5) else base
        summary_grp["Missing gender %"] = summary_grp.apply(lambda r: _pct_cell(r["Missing_gender_n"], r["Total"], FLAG_EMOJI), axis=1)
        summary_grp["Missing GPA %"] = summary_grp.apply(lambda r: _pct_cell(r["Missing_GPA_n"], r["Total"], FLAG_EMOJI), axis=1)
        summary_grp["Incomplete physical %"] = summary_grp.apply(lambda r: _pct_cell(r["Incomplete_physical_n"], r["Total"], FLAG_EMOJI), axis=1)
        summary_disp = summary_grp.rename(columns={"School_disp": "School"})[["School", "Sport", "Level", "Missing gender %", "Missing GPA %", "Incomplete physical %"]]
        summary_disp = summary_disp.sort_values(["School", "Sport", "Level"])
        st.markdown("**Summary: missing data &gt;50% of athletes**")
        st.dataframe(summary_disp, use_container_width=True, hide_index=True)
        st.caption("Percentages shown; 🚩 and red = more than half of athletes in that school/sport/level have that type of missing data.")

        st.divider()
        # Flag: Gender = Other (missing gender from coach)
        other_gender = display_df[display_df["Gender"] == "Other"]
        if len(other_gender) == 0:
            st.success("No missing-gender flags in the current data. Every athlete has Boys/Girls recorded.")
        else:
            other_gender = other_gender.copy()
            other_gender["School_disp"] = other_gender["School"].apply(display_school_name)
            flag_school_sport = (
                other_gender.groupby(["School_disp", "Sport", "Level"], as_index=False)
                .agg(Other_gender_count=("STUDENT ID", "count"))
            )
            flag_school_sport = flag_school_sport.rename(columns={"School_disp": "School"})
            flag_school_sport = flag_school_sport.sort_values("Other_gender_count", ascending=False)
            st.markdown("**Missing gender (Other)** — coach did not record gender for these athletes:")
            st.dataframe(flag_school_sport, use_container_width=True, hide_index=True)
            st.caption(f"Total athletes with missing gender in current view: **{len(other_gender)}**")

        st.divider()
        # Flag: Missing GPA
        missing_gpa = display_df[display_df["GPA"].isna()]
        if len(missing_gpa) == 0:
            st.success("No missing-GPA flags in the current data. Every athlete has a GPA recorded.")
        else:
            missing_gpa = missing_gpa.copy()
            missing_gpa["School_disp"] = missing_gpa["School"].apply(display_school_name)
            flag_gpa = (
                missing_gpa.groupby(["School_disp", "Sport", "Level"], as_index=False)
                .agg(Missing_GPA_count=("STUDENT ID", "count"))
            )
            flag_gpa = flag_gpa.rename(columns={"School_disp": "School"}).sort_values("Missing_GPA_count", ascending=False)
            st.markdown("**Missing GPA** — coach did not record GPA for these athletes:")
            st.dataframe(flag_gpa, use_container_width=True, hide_index=True)
            st.caption(f"Total athletes with missing GPA in current view: **{len(missing_gpa)}**")

        st.divider()
        # Flag: Missing or incomplete physicals (anything other than Yes / Approved)
        incomplete_physical = display_df[display_df["PHYSICAL"].apply(physical_status) != "YES"]
        if len(incomplete_physical) == 0:
            st.success("No missing/incomplete physical flags. Every athlete has a physical marked Yes or Approved.")
        else:
            incomplete_physical = incomplete_physical.copy()
            incomplete_physical["School_disp"] = incomplete_physical["School"].apply(display_school_name)
            flag_physical = (
                incomplete_physical.groupby(["School_disp", "Sport", "Level"], as_index=False)
                .agg(Incomplete_physical_count=("STUDENT ID", "count"))
            )
            flag_physical = flag_physical.rename(columns={"School_disp": "School"}).sort_values("Incomplete_physical_count", ascending=False)
            st.markdown("**Missing or incomplete physicals** — anything other than Yes / Approved (e.g. blank, pending, no date):")
            st.dataframe(flag_physical, use_container_width=True, hide_index=True)
            st.caption(f"Total athletes with missing/incomplete physical in current view: **{len(incomplete_physical)}**")

    with tab5:
        st.subheader("Budget Request")
        st.markdown("""
**OUSD OAL Middle School Athletics Data Center**  
*District-Wide Eligibility + Compliance + Retention Metrics (17 Middle Schools)*

- **Requestor / Sponsor:** OAL Middle School Athletic Commissioner  
- **Vendor:** L and Q Consultants (Quoc Tran)  
- **Schools Covered:** 17 OUSD middle schools (OAL)  

**Data Source(s):**
- OUSD shared Google Drive folder of school roster spreadsheets (existing)
- “OAL Middle School Sports Command Center 2026” Google Sheet (existing), with tabs for:
  - Certification completion %
  - Forfeit count
  - Game compliance rate
  - Coach retention rate
  - Student return rate

**Service Type:** Professional / Consultant Services (data integration + dashboard development)

---

### 1) Purpose

Request funding to formalize and productionize a district-wide athletics data dashboard already developed as a no-cost pilot, and to expand the dashboard to include commissioner-defined compliance and retention metrics tracked in the “OAL Middle School Sports Command Center 2026” Google Sheet.

This project supports OUSD athletics by improving district visibility into participation, eligibility readiness, certification compliance, forfeits, game compliance, and program retention across all middle school sites.

---

### 2) Background: Work Completed (No-Cost Pilot)

To validate feasibility and deliver immediate value, L and Q Consultants completed an initial build at no cost as a preliminary assessment.

**A. District-wide ETL from legacy Google Sheets (already completed)**
- Automated extraction from a shared Google Drive folder containing roster spreadsheets using Google Drive + Google Sheets APIs
- Normalized inconsistent roster tabs/templates into a consolidated dataset
- Data cleaning/validation to handle common formatting inconsistencies across coaches and sites

**B. Dashboard application (already completed)**  
A working internal dashboard was built to provide district-wide visibility and exports:

*Metrics already delivered:*
- Participation by Sport
- Participation by Gender
- GPA average by School
- Medical eligibility (Physicals cleared)

*Operational features already delivered:*
- Global filters (School, Level, Season, Gender; plus Team parsing where applicable)
- Detailed roster table (downloadable CSV export)
- Site spot-check drilldowns
- Data quality “Flags” tab (missing GPA, missing gender, incomplete physicals)

*Unbilled pilot effort completed:* ~7 hours (4:00pm–11:00pm)  
*Standard consultant rate for funded work:* $100/hour

---

### 3) Funded Scope: Add Commissioner “Command Center 2026” Metrics + Production Support

**Phase 1 — Integrate “Command Center 2026” tabs into the dashboard**
- **Certification completion %** — Pull from Command Center tab; display district and site-level completion % by season (and by sport if present); add “missing data” flags where schools/coaches have not reported.
- **Forfeit count** — Pull forfeits from Command Center tab; display forfeits by school/sport/season + trend; add flags for missing/unknown entries.
- **Game compliance rate** — Pull compliance rates; display by school/sport/season; add drill-down to identify lowest compliance areas.
- **Coach retention rate** — Pull coach roster/retention fields; compute retention roll-forward if tab provides both periods; display retention by school and sport.
- **Student return rate** — Pull student return metrics and/or compute from roster history; display return rate by school/sport/season + district summary; add flags for incomplete reporting.

**Phase 2 — Dashboard enhancements + governance**
- Add a new “Command Center Metrics” section/tab in the dashboard.
- Add KPI tiles and charts for the five metrics.
- Add “data freshness” timestamp and “coverage/completeness” indicators for each metric tab.
- Add exportable reports for follow-up (e.g., low certification completion, high forfeits, low compliance, retention concerns).

**Phase 3 — Deployment + training + stabilization**
- Provide commissioner training (60–90 minutes).
- Provide a short runbook: how to refresh data, required inputs, what flags mean.
- Stabilization support through initial reporting cycle.

---

### 4) Deliverables

- Updated OAL Athletics Data Center dashboard incorporating five Command Center 2026 metric tabs
- Automated data refresh workflow from both roster folder sheets (17 schools) and Command Center 2026 sheet tabs
- Data-quality + completeness reporting (flags + coverage %)
- Exports for reporting and coach follow-ups
- Documentation + commissioner training
- Initial stabilization support period

---

### 5) Timeline (4 weeks total)

- **Week 1:** Confirm tab schemas + definitions; build ingestion from Command Center sheet  
- **Weeks 2–3:** Implement metrics + dashboard UI + QA with commissioner  
- **Week 4:** Production release + training + first reporting cycle support  

---

### 6) Budget Request

**Option A — Fixed Fee (recommended)**  
- **Implementation (Phases 1–3):** $9,500 one-time  
- Covers: integrating 5 Command Center metric tabs, dashboard updates, completeness flags, exports, documentation, training, and stabilization.  
- **Optional ongoing support:** $750/month (template changes, troubleshooting, incremental improvements, seasonal refresh support)

**Option B — Hourly with Not-To-Exceed (NTE)**  
- **Rate:** $100/hour  
- **Not-to-exceed cap:** $10,000 (100 hours)  
- Pilot work already completed remains no-cost.

---

### 7) Key Assumptions

- The five new metrics will be sourced from the existing “OAL Middle School Sports Command Center 2026” Google Sheet tabs maintained by the commissioner.
- Dashboard will include completeness indicators and flags so missing or inconsistent entries do not silently distort district reporting.
- Student-level data remains under OUSD-authorized access controls.

---

### 8) Requested Action

Approve funding to initiate a consultant services engagement with L and Q Consultants to productionize the existing district-wide dashboard and integrate the commissioner’s Command Center 2026 compliance and retention metrics for reporting across 17 middle schools.
""")

else:
    st.info("👈 Run Deep Scan from the sidebar to begin.")