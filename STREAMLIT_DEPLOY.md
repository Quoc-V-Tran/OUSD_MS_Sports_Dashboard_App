# Step-by-step: Publish this app on Streamlit Community Cloud

Follow these steps to get your OAL dashboard live and share the link with the commissioner.

---

## Step 1: Push your code to GitHub

1. Open Terminal (or Command Prompt) and go to your project folder:
   ```bash
   cd /Users/quoctran/Documents/OUSD_dashboard_App
   ```

2. If this folder is **not** yet a git repo:
   ```bash
   git init
   git add app.py requirements.txt README.md .gitignore STREAMLIT_DEPLOY.md
   git commit -m "OAL Sports Data Center MVP"
   ```

3. Create a **new repository** on GitHub (if you haven’t already):
   - Go to [github.com](https://github.com) → **+** (top right) → **New repository**
   - Name it (e.g. `OUSD_dashboard_App`), leave it empty (no README), click **Create repository**

4. Connect your local folder to GitHub and push (replace `YOUR_USERNAME` and `YOUR_REPO` with your GitHub username and repo name):
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git branch -M main
   git push -u origin main
   ```
   - **Important:** Do **not** add `service_account.json` to git. It’s in `.gitignore`, so it won’t be pushed. Your credentials stay only on your computer.

---

## Step 2: Sign in to Streamlit Community Cloud

1. Go to **https://share.streamlit.io**
2. Click **Sign up** or **Sign in**
3. Choose **Continue with GitHub** and authorize Streamlit to access your GitHub account

---

## Step 3: Create a new app

1. On the Streamlit Cloud dashboard, click **New app**
2. Fill in:
   - **Repository:** `YOUR_USERNAME/YOUR_REPO` (select your repo from the list)
   - **Branch:** `main` (or the branch you use)
   - **Main file path:** `app.py`
3. Leave **Advanced settings** collapsed for now
4. Click **Deploy!**
5. Wait a few minutes. The first deploy may show an error because secrets aren’t set yet — that’s expected. Go to the next step.

---

## Step 4: Add your Google service account secret

The app needs your Google credentials to read the roster folder. You’ll paste them as “Secrets” in Streamlit (so they’re not in your code or repo).

1. On your **deployed app page** on share.streamlit.io, click the **⋮** (three dots) or **Manage app** → **Settings**
2. Open the **Secrets** section
3. You’ll see a text box for **Secrets**. Use **one** of these two formats.

   **Option A — Paste JSON (easiest)**  
   In the Secrets box, type the key, then paste your **entire** `service_account.json` on one line (or as valid JSON) inside triple quotes:

   ```toml
   gcp_service_account = '''
   {"type": "service_account", "project_id": "your-project-id", "private_key_id": "...", "private_key": "-----BEGIN PRIVATE KEY-----\\nYOUR_KEY_HERE\\n-----END PRIVATE KEY-----\\n", "client_email": "your-sa@project.iam.gserviceaccount.com", "client_id": "...", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_x509_cert_url": "..."}
   '''
   ```

   - Open your local `service_account.json`, copy the **whole** contents (one line is fine).
   - Replace newlines inside `private_key` with `\n` (backslash-n) so it’s one line, or keep the JSON valid.
   - Paste that between the `'''` quotes. The app accepts either a JSON string or a TOML object.

   **Option B — TOML section**  
   Alternatively, list each key from your JSON (use your real values):

   ```toml
   [gcp_service_account]
   type = "service_account"
   project_id = "your-project-id"
   private_key_id = "abc123..."
   private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_KEY_LINES\n-----END PRIVATE KEY-----\n"
   client_email = "your-sa@project.iam.gserviceaccount.com"
   client_id = "123456789"
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/..."
   ```

4. Click **Save** (or **Update**). The app will redeploy automatically.

---

## Step 5: Open your app and run a scan

1. Open the app URL Streamlit gave you (e.g. `https://your-app-name.streamlit.app`)
2. In the **sidebar**, click **🚀 Run Deep Scan**
3. Wait for the scan to finish. You should see the dashboard with summary metrics and tabs
4. If you see an error about credentials, double-check Step 4 (no extra spaces, valid JSON/TOML, key name is exactly `gcp_service_account`)

---

## Step 6: Share the link with the commissioner

- Copy the app URL from your browser and send it to the commissioner.
- Tell them to click **Run Deep Scan** the first time (and whenever they want fresh data).
- They can use all tabs: Dashboard, Detailed Data, Site Spot-Check, Flags, and Budget Request.

---

## Troubleshooting

| Problem | What to do |
|--------|------------|
| App shows “No credentials found” or “Current secret keys: (none)” | Secrets didn’t load. In **Settings → Secrets**, the key must be **exactly** `gcp_service_account` (all lowercase, no spaces). Use Option B (TOML section) if Option A gives parsing errors. Click **Save** and wait for the app to redeploy. |
| App shows “Current secret keys: […]” but not `gcp_service_account` | You have other keys but not the right one. Add a **new** key named exactly `gcp_service_account` (copy-paste the name to avoid typos). |
| “Secrets key 'gcp_service_account' is set but invalid” | The value is wrong. For JSON: must be one valid JSON object (escape quotes inside or use one line). For TOML: must include `type`, `project_id`, `private_key`, `client_email` at minimum. Fix the value and Save. |
| “Scan failed” or API error | Confirm the service account has **Drive** and **Sheets** access to the OUSD roster folder. Check that the folder ID in `app.py` is correct. |
| App won’t deploy / build error | Check that `requirements.txt` is in the repo and that the main file path is exactly `app.py`. |

---

## Summary checklist

- [ ] Code pushed to GitHub (no `service_account.json` in the repo)
- [ ] Signed in at share.streamlit.io with GitHub
- [ ] New app created: your repo, branch `main`, main file `app.py`
- [ ] Secrets added: `gcp_service_account` with your service account JSON or TOML
- [ ] App redeployed and “Run Deep Scan” works
- [ ] App URL shared with commissioner
