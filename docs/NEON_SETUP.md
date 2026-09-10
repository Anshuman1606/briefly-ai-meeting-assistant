# PostgreSQL for the Streamlit deployment

Neon is the proposed database provider for the initial pilot. Its Free plan does not require a credit card; review current limits before adding production data. No Neon project has been created for this release yet. [Current pricing](https://neon.com/pricing).

1. Sign in to the [Neon console](https://console.neon.tech/) and create a project on the Free plan. Complete any account agreements yourself.
2. Choose a region appropriate for the application and your data requirements. Use a dedicated database for Briefly.
3. Open the project's **Connect** dialog. Select the intended database and role. For this small deployment, use a direct connection initially by disabling **Connection pooling**; this also keeps schema migration behavior straightforward.
4. Copy the complete PostgreSQL connection string, preserving its TLS parameters. Store it as `DATABASE_URL` in Streamlit app secrets. Briefly accepts the `postgresql://` format supplied by Neon and selects the psycopg driver automatically.
5. Set `APP_ENV="production"`, `ALLOW_SIGNUP=false`, and `BRIEFLY_EMBEDDED_WORKER=true`. Leave optional AI provider keys unset until configured.
6. Supply the same database connection through a trusted operator environment and run `python -m briefly.cli create-owner`. The CLI prompts privately for the owner's password. It does not load Streamlit's secrets file automatically.
7. Deploy, create a sample meeting, and verify that its results remain after restarting the Streamlit app.

Never paste database credentials into GitHub files or chat. A connection string includes the database password. The [Neon connection guide](https://neon.com/docs/connect/connect-from-any-app) explains the Connect dialog and TLS configuration.

The Free plan is for the initial pilot; it does not establish backup, recovery, availability, or capacity requirements for an enterprise release. See [DEPLOYMENT.md](DEPLOYMENT.md) for those release checks.
