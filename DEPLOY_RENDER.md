# Deploy Bethuel Sang Portfolio to Render

This version is prepared for Docker + Render.

## Why this version uses persistent storage

The portfolio Admin writes updates to JSON files and uploads to `assets`.
Render services use an ephemeral filesystem by default, so normal container files
can disappear after a restart or redeploy. This deployment version stores your
editable `data` and `assets` under `/app/storage`, which is the persistent disk.

## Step 1 — Test with Docker locally (optional)

Install Docker Desktop.

Create `.env` from `.env.example` and choose a strong Admin password.

Then:

```powershell
docker compose up --build
```

Open:

http://localhost:8501

Stop:

```powershell
docker compose down
```

Your Docker test data is stored in the local `storage` folder.

## Step 2 — Upload the project to GitHub

Create a new GitHub repository, for example:

bethuel-portfolio

Upload the CONTENTS of this folder to the repository root.

Important:
- Do NOT upload `.env`
- Do NOT create `.streamlit/secrets.toml` in the public repository
- `data/admin_auth.json` is intentionally ignored
- `render.yaml` and `Dockerfile` should be at the repository root

## Step 3 — Deploy using Render Blueprint

1. Sign in to Render.
2. Open Blueprints.
3. Create a new Blueprint instance.
4. Connect the GitHub repository containing this project.
5. Render reads `render.yaml`.
6. When Render asks for `ADMIN_PASSWORD`, enter a NEW strong password.
7. Confirm the service creation.

The supplied Blueprint uses:
- Docker
- Starter web service
- Frankfurt region
- 1 GB persistent disk mounted at `/app/storage`

## Step 4 — Wait for deployment

Render builds the Docker image and starts Streamlit.

When successful you receive a public URL similar to:

https://bethuel-sang-portfolio.onrender.com

## Updating the website later

Code/design changes:
1. Change files locally.
2. Push them to GitHub.
3. Render redeploys from GitHub.

Portfolio Admin changes:
- Profile changes
- Projects
- CV data
- Uploaded screenshots
- Password reset

are written to the persistent disk and remain there across normal restarts/redeploys.

## Important

Do not use `ChangeMe123!` as the internet-facing Admin password.
Enter a strong password when Render prompts for `ADMIN_PASSWORD`.

The first cloud run creates `data/admin_auth.json` on the persistent disk using
the password you supplied to Render. If you later change the password from the
Security tab, the changed password remains on the disk.

## Free alternative

Streamlit Community Cloud is simpler and free, but this portfolio's Admin edits
are filesystem writes. It is better suited to a repository-driven version where
updates are committed to GitHub rather than edited persistently through Admin.
For the current Admin workflow, Render + persistent storage is the safer fit.
