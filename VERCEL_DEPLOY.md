# Vercel temporary test deployment

Vercel can run the CampusPulse Flask application as a Python Web Function. The repository now includes:

- `wsgi.py` — Vercel entry point exporting the Flask `app`
- `requirements.txt` — runtime dependencies
- `vercel.json` — Flask function configuration
- `.python-version` — Python 3.12

## Important limitation

This test deployment uses SQLite at `/tmp/campuspulse-vercel.db`. Vercel function filesystems are ephemeral, so test data can disappear during a cold start, redeploy, or function restart. Use it only for a disposable reality test. Do not use real college data.

## 1. Push the prepared files to GitHub

From the repository root, review the changes and commit them:

```bat
cd /d "C:\Users\edwin\Downloads\KERALA_AI_TUITION_WEB"
git status
git add wsgi.py requirements.txt vercel.json .python-version VERCEL_DEPLOY.md .gitignore college_event_management/app/views/base.html
git commit -m "Prepare CampusPulse for Vercel test deployment"
git push origin main
```

The GitHub repository is:

```text
https://github.com/edwinjanil5/college-event-system
```

## 2. Import the repository into Vercel

1. Open https://vercel.com/new
2. Sign in to the Vercel account.
3. Choose **Add New → Project**.
4. Import `edwinjanil5/college-event-system` from GitHub.
5. Keep the root directory as `/`.
6. Confirm that Vercel detects **Flask**. Do not add a custom build command.
7. Add the environment variables below.
8. Click **Deploy**.

## 3. Environment variables

Set these in Vercel under **Project Settings → Environment Variables** for both Preview and Production:

```text
CAMPUSPULSE_BROWSER=1
AUTO_CREATE_DB=1
CAMPUSPULSE_DATABASE_URL=sqlite:////tmp/campuspulse-vercel.db
REPORTS_FOLDER=/tmp/reports
SESSION_COOKIE_SECURE=1
```

Generate a long random Flask secret locally, for example:

```bat
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set the generated value as:

```text
SECRET_KEY=the-generated-value
```

Never put `SECRET_KEY`, passwords, or service credentials in GitHub.

## 4. After deployment

Vercel will provide a URL similar to:

```text
https://college-event-system.vercel.app
```

Test:

```text
/health
/
/contact
/login
/register
/how-to-use
```

Student and Organizer accounts can be created through public registration. The local CLI cannot provision accounts inside Vercel's temporary SQLite database; Admin/HoD test provisioning requires a separate protected bootstrap flow and should not be added until the temporary test is confirmed.

## CLI alternative

After installing and authenticating Vercel locally:

```bat
npm install -g vercel
vercel login
vercel
```

Use `vercel --prod` only after checking the preview deployment.

## Clean up

When testing is complete, delete the Vercel project or disable its deployment. Then remove any temporary Vercel environment variables containing secrets.
