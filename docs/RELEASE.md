# Streamlit release handoff

The application is published in the private [GitHub repository](https://github.com/Anshuman1606/briefly-ai-meeting-assistant) and prepared for Streamlit Community Cloud. The hosted application is not live yet.

## Release settings

| Setting | Value |
| --- | --- |
| Repository root | This `briefly` directory |
| Deployment branch | `codex/briefly` |
| Entrypoint | `app.py` |
| Python | `3.13` |
| Dependency manifest | `requirements.txt` |
| Runtime configuration | `.streamlit/config.toml` |
| Secret template | `.streamlit/secrets.toml.example` |
| Database | External PostgreSQL; TLS according to the provider's instructions |
| Background processing | Embedded worker enabled on Community Cloud |

Use the actual repository URL and deployed commit in the deployment record once GitHub and Streamlit are connected. Do not publish a generated database, model cache, real secrets, or test recordings.

## Checks completed locally

- 73 automated tests passed, including service authorization, workspace isolation, migrations, job recovery, and Streamlit interface workflows.
- Python lint passed and installed dependencies were consistent.
- A runtime dependency audit covered 53 packages and reported no known vulnerabilities at implementation time. Re-run the audit in CI for the release.
- A real audio upload was transcribed with local Whisper `tiny.en`, analyzed, and saved successfully.
- TXT, JSON and PDF reports were generated. English and Hindi Unicode PDF generation succeeded.
- The local Streamlit health endpoint returned HTTP 200.

GitHub Actions also passed the PostgreSQL 17 integration test on 2026-09-10, covering migrations, tenant isolation, PDF/JSON exports, and persistence after a real database restart. The [verified CI run](https://github.com/Anshuman1606/briefly-ai-meeting-assistant/actions/runs/34456624224) tests code release `9d1d5a76e890996a43b521e85191967a052a625c`.

These checks do not establish an enterprise SLA, production load capacity, or compliance certification. The full Docker deployment, live Mistral/Sarvam requests, organization SSO, and hosted browser checks remain unverified until their services are available. PDF generation was exercised; a separate visual layout review was not performed.

## Account-dependent steps still required

1. Completed: private GitHub repository created under `Anshuman1606`.
2. Completed: release pushed and GitHub Actions passed, including the PostgreSQL integration job.
3. Connect the repository in Streamlit Community Cloud.
4. Configure a dedicated PostgreSQL connection in app secrets. Keep `APP_ENV="production"` and `ALLOW_SIGNUP=false`.
5. Provision the initial owner with the operator CLI, or configure verified organization OIDC. Enable optional provider integrations only after their credentials and limits are configured.
6. Deploy `app.py`, verify persistence and the hosted workflow, and record the real URL and commit in `docs/DEPLOYMENT.md`.

Follow [DEPLOYMENT.md](DEPLOYMENT.md) for the exact configuration, verification and rollback steps.
