# Briefly

A Python meeting and video assistant built with Streamlit. Bring a transcript, import available YouTube captions, or enable audio transcription; review summaries and decisions, track action items, ask questions with source citations, and export the report.

This project targets a controlled organizational pilot. It includes application access controls, persistent jobs, PostgreSQL support, migrations, tests, and deployment packaging. A public deployment, load validation, disaster-recovery exercise, or compliance certification is not implied by the code being present. The release status and hosted URL must be recorded after deployment in [the deployment record](docs/DEPLOYMENT.md#deployment-record).

## Run locally

Use Python 3.13 and open a terminal in this repository's root directory:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open <http://localhost:8501>. With no secrets configured, the app uses a local SQLite database in `data/`, the embedded worker, and labeled extractive analysis. Start with the sample meeting or create a local account. No provider key or model download is needed for this text workflow. Keep this local mode for sample data and development; it permits signup and demonstration access.

The database schema is initialized on startup through the versioned migrations. Start from a clean database, or follow the migration procedure below for an existing deployment. Do not commit the generated database, uploads, or secrets.

## What is included

| Capability | Implementation |
| --- | --- |
| Transcript ingestion | Paste text; 40–100,000 characters per transcript. |
| YouTube import | Captions fetched from validated YouTube URLs. Restricted videos, missing captions, or host blocking can prevent import; paste a transcript in those cases. |
| Media transcription | Optional local Whisper for supported audio/video, or Sarvam for Hindi/Hinglish PCM WAV. Uploads are limited to 25 MB and media to two hours; shorter files suit shared hosting. |
| Analysis | Summaries, decisions, unresolved questions, and action items with supporting evidence. Optional Mistral generation; extractive analysis otherwise. |
| Meeting questions | Answers from retrieved transcript excerpts with source citations; insufficient evidence is handled explicitly. |
| Action tracking | Owners and editors can mark actions complete. Owners and dates extracted from speech still need review. |
| Workspace access | Owner, editor, and viewer roles; service-layer authorization; workspace switching; member removal revokes affected sessions. |
| Authentication | Argon2 password hashes and eight-hour database sessions, or native Streamlit OIDC with verified email and a domain allowlist. |
| Exports | UTF-8 TXT, JSON, and PDF with bundled Latin and Devanagari fonts. |
| Operations | Database-backed jobs, leases and heartbeats, bounded retries, quotas, audit events, archive recovery, and retention maintenance. |

This application processes supplied content; it does not join calls, record live meetings, or download arbitrary YouTube videos. A source citation helps a reviewer locate evidence; it does not guarantee that a generated interpretation is correct.

## Optional AI and speech providers

Configure root keys in ignored `.streamlit/secrets.toml` for Streamlit, or environment variables for the administrative CLI and standalone worker. Use [.streamlit/secrets.toml.example](.streamlit/secrets.toml.example) as the hosted configuration reference.

| Integration | Configuration |
| --- | --- |
| Mistral analysis and answers | Set `MISTRAL_API_KEY`; optionally set `MISTRAL_MODEL` (default `mistral-small-latest`). Model aliases may change; select an approved model for repeatable releases. |
| Sarvam speech | Set `TRANSCRIPTION_BACKEND=sarvam` and `SARVAM_API_KEY`; optional `SARVAM_MODEL` defaults to `saaras:v3`. This adapter accepts PCM WAV with Hindi, Hinglish, or automatic language selection. |
| Local Whisper | Install `requirements-whisper.txt`; set `TRANSCRIPTION_BACKEND=whisper`. Default model is `small`, CPU device, and `int8` compute. |

Provider-enabled processing sends the relevant transcript, question, or audio to that provider. Configure keys on the server and use content you are authorized to process. These integrations have separate service accounts, quotas, and costs.

Whisper weights are **not downloaded by default**. Provision a model directory and set `WHISPER_MODEL` to its path, or explicitly enable `WHISPER_ALLOW_DOWNLOAD=true` during setup. A first transcription then downloads the selected model. After provisioning, disable downloads and restart the worker. Persist the model cache or mount a provisioned model directory on container hosts. Optional package installation alone does not install weights, and local speech inference has not been assumed to fit Community Cloud resource limits.

```sh
python -m pip install -r requirements-whisper.txt
```

## Streamlit Community Cloud deployment

1. Publish this directory as a GitHub repository. Keep secrets and local data excluded.
2. Sign in to [Streamlit Community Cloud](https://share.streamlit.io/) and authorize access to that repository.
3. Create an app using the intended branch and `app.py`; choose Python **3.13** in Advanced settings.
4. Paste the populated secrets example into Advanced settings. A persistent pilot needs `APP_ENV="production"`, an external PostgreSQL `DATABASE_URL`, `ALLOW_SIGNUP=false`, and `BRIEFLY_EMBEDDED_WORKER=true`.
5. Provision the initial authorized account as described below, deploy, and complete the hosted smoke tests in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

The remaining account-dependent steps require access to the user's GitHub/Streamlit accounts and a real PostgreSQL service. This repository does not contain those credentials or a pre-existing hosted URL. Community Cloud's UI supplies the actual `streamlit.app` URL when deployment succeeds. [Official deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

Community Cloud is suitable for evaluating this workflow with bounded workloads. It can sleep, has shared resource limits, and provides no application filesystem persistence guarantee. Use external PostgreSQL and the operations runbook. For continuous workers and stronger availability requirements, operate the container topology with an HTTPS ingress, monitoring, and database backups. [Community Cloud operations](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app), [runtime file persistence](https://docs.streamlit.io/develop/concepts/configuration/serving-static-files).

## Initial account and organizational sign-in

For a password-authenticated pilot, supply the production database URL securely in your administrative terminal's environment, then run:

```sh
export APP_ENV=production
export AUTH_MODE=password
export ALLOW_SIGNUP=false
python -m briefly.cli create-owner
```

`DATABASE_URL` must already be set in that shell by your secret manager or secure environment setup. The CLI reads environment variables, not Streamlit's TOML file. It prompts for username, email, workspace, and a confirmed password without echoing the password. It creates an owner and closes the temporary provisioning session. `ALLOW_SIGNUP` remains disabled for the web app.

For a shared production team, use `AUTH_MODE=oidc`, configure Streamlit's `[auth]` block, and require an approved `OIDC_ALLOWED_DOMAINS` allowlist. Users first sign in through the identity provider; an owner can then add their registered email as an editor or viewer. Production password mode does not support adding team members because password registrations do not verify email ownership. The [deployment runbook](docs/DEPLOYMENT.md#configure-secrets-and-identity) explains OIDC setup and session behavior.

## Rehearse with PostgreSQL and separate workers

The Compose configuration runs Streamlit, an independent worker, and PostgreSQL 17. The web port binds to localhost; the database is only on the Compose network. The database volume persists across `docker compose down`. This is a local deployment rehearsal, with no HTTPS ingress or managed backups configured.

Generate an ignored `.env` with a unique local database password. The command creates a new file with owner-only permissions and refuses to overwrite an existing file:

```sh
python - <<'PY'
import os
import secrets

password = secrets.token_hex(32)
content = (
    "POSTGRES_DB=briefly\n"
    "POSTGRES_USER=briefly\n"
    f"POSTGRES_PASSWORD={password}\n"
    f"DATABASE_URL=postgresql+psycopg://briefly:{password}@db:5432/briefly\n"
)
with os.fdopen(os.open(".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
    output.write(content)
print("Created .env. Keep it private and out of source control.")
PY
docker compose build
docker compose up -d db
docker compose run --rm web python -m briefly.cli create-owner
docker compose up -d web worker
```

Visit <http://localhost:8501> and sign in. `BRIEFLY_EMBEDDED_WORKER=false` keeps web processes from starting workers; the worker runs `python -m briefly.worker`. Inspect service state and logs with `docker compose ps` and `docker compose logs --tail=100 web worker`. The web health check only confirms the Streamlit process responds; verify job completion and database access separately.

The Compose database user initializes the local database and is privileged. For a real hosted deployment, use dedicated database credentials, reviewed migration permissions, TLS, and backups. Changing `.env` does not change a password already stored in the PostgreSQL volume. Rotate that password through PostgreSQL before updating application credentials. Never use `docker compose down --volumes` when data must be retained.

For OIDC in containers, mount a populated `.streamlit/secrets.toml` read-only into `/app/.streamlit/secrets.toml` on the web service, register the HTTPS callback URL, and configure the root environment settings. The provided Compose file does not mount a secrets file automatically. Optional Whisper builds use `INSTALL_WHISPER=true`; provision persistent weights and measure memory before using them.

## Checks and maintenance

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m ruff check --select E,F --ignore E501 .
python -m pip_audit -r requirements.txt
```

Tests exercise authentication, workspace boundaries, role enforcement, job recovery, quotas, provider failure handling, source grounding, and exports without making real provider calls. The GitHub workflow also validates against an isolated PostgreSQL instance. Optional providers, OIDC, cloud deployment, and representative load still need deployment-specific checks. If Whisper is enabled, additionally audit `requirements-whisper.txt` and test the actual speech path with provisioned weights.

Dependency files pin the direct libraries validated for this release. They are not a complete transitive lock with package hashes. CI resolves and audits dependencies on each run; capture the resolved installation for a release, review updates, and use a full platform-specific lock and pinned container digest if required by your release policy. An audit only covers the advisories available when it runs.

Administrative commands use the selected database and must run from a trusted operator environment:

```sh
python -m briefly.cli init
python -m briefly.cli maintenance
python -m briefly.cli restore --meeting-id THE_ARCHIVED_MEETING_ID
```

Owners archive meetings in the application. Maintenance permanently purges meetings archived for more than 30 days and clears expired authentication/rate-limit records. It does not delete active meetings merely because they are old, and it does not automatically remove failed uploads. Run it through your operations scheduler; Community Cloud does not provide a continuously running scheduler for this app. Restore is possible only before the archived record is purged. Audit events are retained separately and need an organization-specific retention/export policy.

## Schema changes and recovery

The `migrations/` directory contains reviewed Alembic migrations; startup applies known migrations and checks for model/schema drift. PostgreSQL startup uses a transaction-level advisory lock to serialize migrations. Unversioned application tables and unsupported migration histories are rejected rather than silently marked current.

Before a release that changes schema, back up the database and rehearse migration and restore on a copy. With `DATABASE_URL` in a trusted shell, `python -m alembic upgrade head` applies the repository migrations. Review generated migration code before committing it; do not use `create_all` or blind migration stamping to update an existing deployment. Keep the previous application commit and record whether its schema compatibility permits rollback. The application does not perform automatic backups or destructive downgrades.

## Project map

```text
app.py                      Streamlit interface
briefly/service.py          Authentication, authorization, persistence, job lifecycle
briefly/intelligence.py     Transcript import, retrieval, provider adapters
briefly/exports.py          TXT, JSON, and Unicode PDF reports
briefly/schema.py           Versioned schema initialization and validation
briefly/worker.py            Standalone worker entrypoint
briefly/cli.py               Trusted operator commands
migrations/                 Reviewed Alembic revisions
tests/                      Automated checks
assets/fonts/               Bundled report fonts and their license
.streamlit/                 Theme and secrets example
.github/workflows/ci.yml     Test and dependency audit workflow
docs/DEPLOYMENT.md           Hosted release and operations runbook
docs/ARCHITECTURE.md         Data flow, controls, and scaling boundaries
```

See [the architecture notes](docs/ARCHITECTURE.md) for the current boundaries and what remains to validate before a wider rollout.
