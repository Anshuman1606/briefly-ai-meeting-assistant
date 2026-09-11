# Deploy Briefly on Streamlit

This runbook targets Streamlit Community Cloud for a controlled pilot. It distinguishes a working demo from a deployment configured for organizational data. Community Cloud hosting and this codebase do not establish an enterprise availability SLA or a compliance certification. The deployment operator must record the actual GitHub repository, deployed commit, application URL, and smoke-test result before reporting the service as live.

## Hosting prerequisites

You need a Streamlit Community Cloud account linked to GitHub and administrative permission on the repository being deployed. Community Cloud must be authorized to read the repository. Private repositories require additional GitHub authorization and a read-only deploy key. These are hosting requirements, separate from authentication inside Briefly. [Streamlit permissions](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/trust-and-security), [GitHub integration requirements](https://docs.streamlit.io/deploy/streamlit-community-cloud/status).

For a persistent team deployment, also supply:

- An external PostgreSQL database, reachable from the host over TLS, with a dedicated application account and backups.
- An identity-provider application if organizational SSO is enabled.
- A provider API key if an optional external AI provider is enabled.
- Named owners for access administration, database recovery, incident response, and dependency updates.

The code repository contains configuration examples, not credentials. Database and API accounts are separate services; their availability, charges, and suitability must be confirmed by the operator.

## Publish the repository

Use the `briefly` project directory as the repository root. Include the Python application, dependency declarations, Streamlit configuration, tests, documentation, and sample data. Exclude `.venv`, local database files, uploaded customer data, caches, and `.streamlit/secrets.toml`.

Run the checks documented in the root README before pushing the deployment branch. Require those checks on pull requests and keep a record of the previous deployed commit for rollback. Test with the same Python version selected in Community Cloud. The recommended dependency manifest is `requirements.txt`; avoid adding a competing deployment manifest that Cloud might choose first. Linux system dependencies, if required, belong in root `packages.txt`. [Dependency discovery](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

## Create the hosted app

1. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) and select the workspace matching the repository owner.
2. Choose **Create app**, then **Yup, I have an app**.
3. Select the actual repository, deployment branch, and `app.py` as the entrypoint.
4. Choose an available subdomain, if desired.
5. Open **Advanced settings**, explicitly select **Python 3.13**, matching this project's validation runtime, and paste the deployment TOML secrets.
6. Save the settings and choose **Deploy**. Watch the build and application logs until the application loads successfully.

Select Python 3.13 explicitly; the deployment form displayed Python 3.14 by default during this release. The deployment page produces the actual `streamlit.app` URL; a proposed subdomain alone is not evidence of deployment. [Deployment workflow](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## Configure secrets and identity

Enter secrets in Community Cloud's app settings; locally, put them in ignored `.streamlit/secrets.toml`. Keep actual credentials out of Git history, screenshots, documentation, and logs. Updating an example does not configure the deployed service. [Community Cloud secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

Start from the following deployment configuration. Every placeholder needs a real value before enabling that integration. Keep root settings above any `[auth]` table in TOML.

```toml
APP_ENV = "production"
DATABASE_URL = "postgresql+psycopg://APP_USER:APP_PASSWORD@DB_HOST:5432/briefly?sslmode=require"
AUTH_MODE = "password"
ALLOW_SIGNUP = true

# Required only for the corresponding optional provider.
# MISTRAL_API_KEY = "replace-with-provider-key"
# MISTRAL_MODEL = "replace-with-approved-model-id"

TRANSCRIPTION_BACKEND = "disabled"
WHISPER_MODEL = "small"
WHISPER_ALLOW_DOWNLOAD = false
# SARVAM_API_KEY = "replace-with-provider-key"

# Keep enabled on Community Cloud, where this app owns its embedded worker.
BRIEFLY_EMBEDDED_WORKER = true
```

| Key | Behavior |
| --- | --- |
| `APP_ENV` | Set `production` for the hosted team pilot. Production requires PostgreSQL and disables the demo. |
| `DATABASE_URL` | Use `postgresql+psycopg://...`; PostgreSQL aliases are normalized by the application. Require TLS according to your database provider's connection instructions. |
| `AUTH_MODE` | `password` by default, or `oidc` for the identity provider integration. |
| `ALLOW_SIGNUP` | Set `true` to display Create account and create separate private workspaces. Set `false` for administrator-provisioned accounts. Provision the initial password owner using `python -m briefly.cli create-owner` from a trusted environment configured for the same PostgreSQL database. |
| `MISTRAL_API_KEY`, `MISTRAL_MODEL` | Configure the Mistral integration. Without a key, output uses the explicitly labeled extractive mode; it is not a provider-generated AI summary. |
| `TRANSCRIPTION_BACKEND` | `disabled` by default, `whisper` for local model inference, or `sarvam` for the Sarvam API. Text transcripts remain usable when audio transcription is disabled. |
| `WHISPER_MODEL` | Local Whisper model name or provisioned model directory; default `small`. Install `requirements-whisper.txt` separately. Validate memory and execution time before enabling on Community Cloud. |
| `WHISPER_ALLOW_DOWNLOAD` | `false` by default. Provision model weights separately, or explicitly set `true` during setup to permit the first transcription to download them. Persist the weights, then disable downloads and restart the worker. |
| `SARVAM_API_KEY` | Needed only when `TRANSCRIPTION_BACKEND = "sarvam"`. |
| `BRIEFLY_EMBEDDED_WORKER` | Keep `true` for the embedded single-thread worker. Set `false` only when a separate worker process is actually deployed. |

Production startup should be treated as incomplete until the PostgreSQL connection, initial authorized account, and selected integrations work. Setting a production flag alone does not verify these services.

The administrative CLI and standalone worker read environment variables. Streamlit's secrets loader makes root TOML settings available to the web app; putting a URL in `.streamlit/secrets.toml` alone does not configure a separate CLI process. Set `DATABASE_URL`, `APP_ENV=production`, and `AUTH_MODE=password` through the operator's trusted environment, then run `python -m briefly.cli create-owner`. The command prompts for the account details and a confirmed password without echoing it. For administrator-provisioned accounts only, keep `ALLOW_SIGNUP=false` in the deployed app. See the [README provisioning instructions](../README.md#initial-account-and-organizational-sign-in).

Production password mode supports the provisioned owner workflow. Adding production team members requires OIDC because locally registered password accounts do not verify email ownership. In OIDC mode, each approved user first signs in through the identity provider; an owner can then add that user's registered email as an editor or viewer in the intended workspace.

For native Streamlit OIDC, set `AUTH_MODE = "oidc"` and a comma-separated `OIDC_ALLOWED_DOMAINS` value containing only approved email domains. The application requires this allowlist and a verified email claim for OIDC account provisioning. Configure the identity provider with the deployed origin and callback URL `https://ACTUAL-APP.streamlit.app/oauth2callback`. The `[auth]` block needs `redirect_uri`, a strong random `cookie_secret`, `client_id`, `client_secret`, and `server_metadata_url`. Use a distinct client or explicitly registered callback for local development. Restrict provider membership before admitting team users.

```toml
# These two settings replace/add to the root settings above.
AUTH_MODE = "oidc"
OIDC_ALLOWED_DOMAINS = "your-company.example"

[auth]
redirect_uri = "https://ACTUAL-APP.streamlit.app/oauth2callback"
cookie_secret = "replace-with-a-strong-random-secret"
client_id = "replace-with-identity-provider-client-id"
client_secret = "replace-with-identity-provider-client-secret"
server_metadata_url = "https://IDENTITY-PROVIDER/.well-known/openid-configuration"
```

The `.example` domain and `IDENTITY-PROVIDER` above are placeholders, not working account settings. For password authentication, Briefly uses Argon2 password hashes and opaque database-backed sessions with an eight-hour lifetime.

OIDC identifies users; application permissions still need enforcement in the data/service layer. Streamlit's identity cookie lasts up to 30 days, and logout in one session does not end sessions already open in other tabs. Organizations with stricter session requirements must account for that behavior. [Authentication behavior](https://docs.streamlit.io/develop/concepts/connections/authentication).

## Persistence and service boundaries

Treat the Community Cloud filesystem and in-process session/cache state as disposable. Local SQLite is useful for development and sample demonstrations; it is not the durable store for an organization's records on this host. Store durable records in the external database. Backups must live outside the application container and a restore must be tested. The Streamlit documentation explicitly does not guarantee persistence for files generated at runtime. [Runtime file persistence](https://docs.streamlit.io/develop/concepts/configuration/serving-static-files).

The following operational limits affect the architecture:

| Host characteristic | Consequence for Briefly |
| --- | --- |
| Apps sleep after 12 hours without traffic | Cold starts are expected; do not depend on the app process for scheduled or continuous work. |
| CPU, memory, and storage limits can change | Keep inputs and concurrency bounded; measure representative workload before broader rollout. |
| Resource exhaustion can throttle or stop the app | Monitor failures and use a host with controlled capacity if availability requirements exceed the observed service. |
| Community Cloud hosts apps in the United States | Confirm data residency before uploading organizational information. |
| Source updates trigger app updates | Require checks and review on the deployment branch. |

These are architectural implications of the documented hosting behavior, not availability guarantees. [Resources, sleeping, and updates](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app), [Hosting limitations](https://docs.streamlit.io/deploy/streamlit-community-cloud/status).

Briefly persists jobs in the database and uses an expiring lease with a heartbeat while processing. The default worker is a single thread embedded in the app process. A restart can leave work waiting for a lease to expire; work does not continue while Community Cloud sleeps. In a container deployment, an independently supervised worker can run with `python -m briefly.worker` while the web process sets `BRIEFLY_EMBEDDED_WORKER=false`. Community Cloud's standard app deployment does not create that separate worker for you.

Uploads are bounded to 200 MB and temporarily stored in the database; the upload payload is removed after successful transcription, before analysis, so an analysis retry can reuse the saved transcript. A failed transcription may retain its upload. Archive those records when appropriate and run `python -m briefly.cli maintenance` from the trusted operator environment to purge records archived for more than 30 days. This command also clears expired sessions and rate-limit records; it does not age out active meetings or audit events. `python -m briefly.cli restore --meeting-id ID` restores an archived record only before it is purged. Schedule maintenance outside the Community Cloud app and define separate audit-retention requirements.

This storage approach suits a pilot. Large media, durable continuous processing, and stronger retention policies need object storage and separately operated workers. External AI calls also depend on the configured provider's availability and quota. The Sarvam adapter supports Hindi/Hinglish PCM WAV; local Whisper is the optional path for the other supported media formats.

## Schema and container deployment

Startup applies the committed Alembic migrations and checks the resulting schema against the models. PostgreSQL migrations are serialized with a transaction-level advisory lock. Existing application tables with no migration history, unsupported versions, and schema drift fail startup. Review an explicit migration/baseline when importing an older database; do not bypass the check by blindly stamping a revision.

Take a database backup before a schema-changing release and rehearse `python -m alembic upgrade head` with `DATABASE_URL` supplied by the operator's environment. The deployment database role needs the permissions required by the reviewed migration. Rehearse rollback compatibility separately; this project does not schedule backups or automatically downgrade schemas.

The repository also includes a non-root Python container image and a Compose rehearsal with PostgreSQL 17, a web process, and a separate worker. Compose requires database secrets in an ignored `.env`, exposes only a localhost web port, and keeps PostgreSQL on its internal network. Follow the [README setup](../README.md#rehearse-with-postgresql-and-separate-workers). For a hosted container deployment, configure HTTPS ingress, a suitably privileged application database role, backups, and monitoring. The Compose database initializer is privileged and intended for local rehearsal.

## Release verification

Perform the following checks against the hosted URL, not just localhost:

- The application loads in a clean browser session without traceback or missing dependency errors.
- The local demonstration completes using only sample data; the production deployment does not expose the demo bypass.
- The configured AI provider completes one small request, or the UI clearly identifies extractive analysis.
- A user can create a record, reload, and retrieve it from the configured durable database.
- A second user cannot read or change another user's or workspace's protected records.
- A user without the required permissions cannot invoke administrative actions.
- TXT, JSON, and PDF exports download successfully and contain the expected records, including any Hindi text used by the team.
- A controlled app restart preserves records in the external database.
- An interrupted job is recovered after its lease expires without losing its stored input.
- Logs contain useful diagnostics without credentials or document content.

Only mark checks as passed after actually running them. Database, OIDC, provider, browser, and multi-user checks that lack configured services remain pending.

## Operations and rollback

Inspect logs through **Manage app**. An application restart can recover a failed process, but it is not a data-recovery method. For an unsuccessful release, revert the deployment branch to the previously validated application commit, let Cloud redeploy it, then repeat smoke tests. Plan data migrations so the previous release can still read the database; otherwise recover through a separately tested migration/restore procedure.

Monitor the application error rate, request latency, provider failures, database connections, and backup age through the services available to the deployment. Establish thresholds based on measured normal use. Rotate credentials through the host's secrets settings and the issuing service. Validate before broadening access.

## Deployment record

Verified hosted release on 2026-09-11:

| Field | Verified value |
| --- | --- |
| GitHub repository | [Anshuman1606/briefly-ai-meeting-assistant](https://github.com/Anshuman1606/briefly-ai-meeting-assistant), private |
| Deployment branch and code commit | `codex/briefly`; `7edd13b9dadea513471f9a1a7cc9470b0ee5d60f` |
| Python version | 3.13, selected in Streamlit and verified in GitHub Actions |
| Hosted application URL | [Briefly](https://briefly-anshuman1606.streamlit.app/) |
| Database | Existing Neon Free project `briefly`, PostgreSQL 18, production branch; TLS and channel binding required |
| Access mode | Password accounts with self-registration enabled (`ALLOW_SIGNUP=true`); each registration creates a separate private workspace. Demo sessions remain disabled; organizational OIDC not configured |
| Processing | Embedded cloud worker; Whisper `tiny` on CPU with int8; model download enabled for ephemeral host restarts |
| Analysis | Extractive analysis; Mistral and Sarvam credentials are not configured |
| GitHub validation | [78 tests, lint, audit and PostgreSQL integration passed](https://github.com/Anshuman1606/briefly-ai-meeting-assistant/actions/runs/34491982783) |
| Hosted checks | Owner sign-in and sample meeting results verified in browser. Cloud worker processed 145,351 characters / 2,401 segments, and transcribed real public speech audio. Retrieval verified a fact in the final section. App woke successfully after inactivity. A separate database connection verified retained records, owner authentication and service TXT/JSON/PDF exports. |
| Backup operations | Neon plan recovery features apply; no independent scheduled backup or disaster-recovery exercise has been configured |
| Rollback baseline | `7edd13b9dadea513471f9a1a7cc9470b0ee5d60f` is the first verified hosted code release; later documentation commits do not change runtime behavior |

Secrets and the owner login are stored outside the repository and release ZIP. No database password or login password belongs in this record. The application's configured capacity is 20 MB of UTF-8 text or 200 MB / 12 hours of media. These upper bounds are not a load-test result; see [LARGE_INPUTS.md](LARGE_INPUTS.md) for batching and hosting limitations. Large uploads temporarily use the limited Neon Free database storage.

Community Cloud may sleep after inactivity. Open the application and choose the wake-up button when shown; meetings remain in external PostgreSQL. This deployment is a functioning pilot, with no enterprise SLA or compliance certification claimed.

### Registration setting

The live app now enables `ALLOW_SIGNUP=true` at the user’s request. Its login page displays **Create account**, with username, email, workspace name and password confirmation. Registration creates a new workspace owned by that user; it does not grant membership in an existing workspace. Email addresses are not verified in password mode. Set this flag to false only when intentionally operating with administrator-provisioned accounts. When the flag is omitted, the service defaults to disabled in production.
