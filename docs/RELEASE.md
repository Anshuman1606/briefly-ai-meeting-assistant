# Streamlit release handoff

The application is published in the private [GitHub repository](https://github.com/Anshuman1606/briefly-ai-meeting-assistant) and deployed at [Briefly on Streamlit](https://briefly-anshuman1606.streamlit.app/).

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

The verified code release is `7edd13b9dadea513471f9a1a7cc9470b0ee5d60f`; see the deployment record for hosting settings. Do not publish a generated database, model cache, real secrets, or test recordings.

## Checks completed locally

- 78 automated tests passed, including service authorization, workspace isolation, migrations, job recovery, and Streamlit interface workflows.
- Python lint passed and installed dependencies were consistent.
- The current runtime dependency audit reported no known vulnerabilities. Re-run the audit in CI for the release.
- A real audio upload was transcribed with local Whisper `tiny.en`, analyzed, and saved successfully.
- TXT, JSON and PDF reports were generated. English and Hindi Unicode PDF generation succeeded.
- The local Streamlit health endpoint returned HTTP 200.

GitHub Actions passed all 78 tests, lint, dependency audit, and PostgreSQL 17 integration checks for [the deployed code release](https://github.com/Anshuman1606/briefly-ai-meeting-assistant/actions/runs/34491982783). Database checks cover migrations, tenant isolation, PDF/JSON exports and persistence after a real database restart.

On the hosted app, the owner signed in and processed a sample meeting. The cloud worker processed a 145,351-character transcript (2,401 segments), retained its final-section evidence for questions, and successfully transcribed real public speech audio using Whisper `tiny`. The app recovered from Community Cloud sleep and displayed its sign-in page again. A separate database reconnection confirmed retained transcripts and owner authentication; service TXT, JSON and PDF exports succeeded against the hosted records.

These checks do not establish an enterprise SLA, production load capacity, or compliance certification. The full Docker deployment, live Mistral/Sarvam requests, and organization SSO remain unverified. PDF generation was exercised; a separate visual layout review was not performed.

## Deployment complete

The private repository is connected to Streamlit, the Neon connection is in private app settings, and the owner account is provisioned with signup disabled. CPU Whisper is enabled. Mistral, Sarvam and organizational OIDC remain optional and unconfigured.

The owner login file is provided separately to the user and is not included in GitHub or the release archive. Follow [DEPLOYMENT.md](DEPLOYMENT.md) for the deployment record, operating limits, verification and rollback.
