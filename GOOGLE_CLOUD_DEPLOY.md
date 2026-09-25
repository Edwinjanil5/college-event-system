# Google Cloud reality-test deployment

This project is prepared for a **Google Cloud Run + Cloud SQL MySQL** test deployment. Cloud Run is used for the web process; Cloud SQL is used for durable data. Do not use the local SQLite file as the Cloud Run database because Cloud Run's filesystem is ephemeral.

The included deployment files are:

- `college_event_management/Dockerfile`
- `college_event_management/entrypoint.sh`
- `college_event_management/requirements-cloud.txt`
- `college_event_management/wsgi.py`

## 1. Prerequisites

You need a Google Cloud project with billing enabled and these APIs enabled:

```text
Cloud Run API
Cloud Build API
Artifact Registry API
Cloud SQL Admin API
Secret Manager API
```

Install and authenticate the Google Cloud CLI on the machine that will deploy:

```text
gcloud init
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Do not paste service-account keys into chat or commit them to the repository.

## 2. Create the container repository

```text
gcloud artifacts repositories create campuspulse --repository-format=docker --location=asia-south1
```

Build and upload the image from the repository root:

```text
gcloud builds submit --tag asia-south1-docker.pkg.dev/YOUR_PROJECT_ID/campuspulse/app:latest college_event_management
```

## 3. Create durable database storage

Create a MySQL Cloud SQL instance and database, then create a database user. Keep the password in a secret, not in a command saved to a file.

The database URL should use the SQLAlchemy form:

```text
mysql+pymysql://DB_USER:DB_PASSWORD@DB_HOST/college_event_db
```

For a private Cloud SQL connection, use the Cloud SQL connector/Auth Proxy or a private IP. Do not expose the database to the public internet.

Create secrets for the database URL and Flask secret key:

```text
gcloud secrets create campuspulse-db-url --data-file=YOUR_SECURE_URL_FILE
gcloud secrets create campuspulse-secret-key --data-file=YOUR_SECRET_KEY_FILE
```

The secret-key file should contain a long random value, not a password or a default development key.

## 4. Run database migrations once

Migrations should be run as a controlled one-off job, not by every web instance. Locally or from a trusted administration environment:

```text
flask --app wsgi:app db upgrade
```

The `RUN_MIGRATIONS=1` environment variable is supported by `entrypoint.sh` for a one-off Cloud Run job. Do not leave it enabled on the normal web service.

## 5. Deploy the web service

Example using a private Cloud SQL connection:

```text
gcloud run deploy campuspulse ^
  --image asia-south1-docker.pkg.dev/YOUR_PROJECT_ID/campuspulse/app:latest ^
  --region asia-south1 ^
  --allow-unauthenticated ^
  --port 8080 ^
  --add-cloudsql-instances=PROJECT_ID:asia-south1:INSTANCE_NAME ^
  --set-env-vars=CAMPUSPULSE_BROWSER=1,AUTO_CREATE_DB=0,FLASK_DEBUG=0,SESSION_COOKIE_SECURE=1,REPORTS_FOLDER=/tmp/reports ^
  --set-secrets=CAMPUSPULSE_DATABASE_URL=campuspulse-db-url:latest,SECRET_KEY=campuspulse-secret-key:latest
```

For a public reality test, `--allow-unauthenticated` allows users to reach the site. The admin and HoD accounts remain protected by their account credentials and CSRF-protected actions.

Reports written to `/tmp` are suitable for a short test but are not permanent. For production, add a Cloud Storage report adapter.

## 6. Reality-test checklist

After deployment, test the public URL:

1. `/health` returns HTTP 200.
2. Homepage loads with the supplied logo and Support page.
3. Student registration and login work.
4. Organizer creates a program; it appears as **Awaiting HoD**.
5. HoD logs in, reviews the details, and sends it to admin.
6. Admin gives final approval.
7. Student registration and feedback work.
8. Assistant answers a website question through the browser.
9. Contact email and phone links work.
10. Logout, report generation, and CSRF-protected actions work.
11. Check Cloud Run logs for database, migration, template, and permission errors.

## 7. Safe operating notes

- Never deploy the repository's `college_event.db` as the production database.
- Keep `SECRET_KEY`, database credentials, and admin passwords in Secret Manager or another secret store.
- Run migrations before changing application traffic.
- Start with one Gunicorn worker and four threads; increase workers only after measuring database connection limits.
- Restrict Cloud SQL networking and review Cloud Run IAM before production use.
- Keep the local SQLite database only for offline/desktop development.
