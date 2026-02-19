# OUSD OAL Middle School Sports Data Center

MVP dashboard for district-wide athletics: rosters, participation, eligibility, and data-quality flags across 17 OAL middle schools. Built for the OAL Middle School Athletic Commissioner.

**Features:** Consolidated roster from Google Drive roster spreadsheets, filters (school / level / season / gender / team), participation and GPA charts, site drill-downs, Flags tab (missing gender, GPA, physicals), Budget Request tab.

---

## Run locally

1. **Clone the repo** (or use your existing copy):
   ```bash
   git clone https://github.com/YOUR_USERNAME/OUSD_dashboard_App.git
   cd OUSD_dashboard_App
   ```

2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Add Google credentials** (do not commit this file):
   - Place your Google Cloud service account JSON key in the project root as `service_account_2.json`.
   - The service account must have **Drive read** and **Sheets read** access to the OUSD roster folder.

4. **Start the app:**
   ```bash
   streamlit run app.py
   ```
   Open the URL shown (e.g. http://localhost:8501). Use **Run Deep Scan** in the sidebar to load roster data.

---

## Deploy to Streamlit Community Cloud (MVP share with commissioner)

1. **Push this repo to GitHub** (ensure `service_account_2.json` is not committed — it’s in `.gitignore`).

2. **Go to [share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.

3. **New app** → choose this repo, branch (e.g. `main`), main file path: `app.py`.

4. **Add secrets** so the app can read Google Drive/Sheets:
   - In the app’s **Settings → Secrets**, add a key `gcp_service_account` with the same structure as your service account JSON (e.g. `type`, `project_id`, `private_key_id`, `private_key`, `client_email`, etc.). You can paste the JSON as TOML or use the [Secrets management](https://docs.streamlit.io/streamlit-community-cloud/deploy-your-app/secrets-management) format.
   - The app uses **either** a local `service_account_2.json` file **or** `st.secrets["gcp_service_account"]`, so the same repo works locally and on Cloud.

5. **Deploy.** After the first run, the commissioner can open the app URL, click **Run Deep Scan**, and use the dashboard.

---

## Repo structure

| File / folder      | Purpose |
|--------------------|--------|
| `app.py`           | Streamlit app (single file). |
| `requirements.txt` | Python dependencies. |
| `service_account_2.json` | **Local only** — Google service account key; do not commit. |
| `.gitignore`       | Excludes secrets and Python/IDE artifacts. |

---

## Notes for commissioner

- **Data source:** OUSD shared Google Drive folder of school roster spreadsheets (read-only).
- **First use:** Click **Run Deep Scan** in the sidebar to load data; you can **Clear cache & rescan** to refresh.
- **Budget / next phase:** See the **Budget Request** tab in the app for the proposed Command Center 2026 integration and funding request.
