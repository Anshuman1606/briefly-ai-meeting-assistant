"""Operator tools. Secrets are entered with getpass, never command-line flags."""

import argparse
import getpass

from sqlalchemy import select

from briefly.models import Meeting
from briefly.service import Service


def main():
    parser = argparse.ArgumentParser(description="Briefly administration")
    parser.add_argument("command", choices=["init", "create-owner", "maintenance", "restore"])
    parser.add_argument("--meeting-id")
    args = parser.parse_args()
    service = Service()
    if args.command == "init":
        print("Database schema initialized.")
    elif args.command == "create-owner":
        if service.auth_mode != "password":
            raise SystemExit("OIDC users are provisioned by verified organization sign-in.")
        username = input("Username: ")
        email = input("Email: ")
        workspace = input("Workspace: ")
        password = getpass.getpass("Password (12+ characters): ")
        if password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        service.signup_allowed = True
        account = service.register(username, email, password, workspace)
        service.logout(account)
        print("Owner account created. Sign in through the app.")
    elif args.command == "maintenance":
        print(f"Purged {service.maintenance()} archived meetings older than 30 days; expired sessions removed.")
    elif args.command == "restore":
        if not args.meeting_id:
            raise SystemExit("Specify --meeting-id for the archived meeting.")
        with service.Session.begin() as session:
            meeting = session.scalar(select(Meeting).where(Meeting.id == args.meeting_id, Meeting.deleted_at.is_not(None)))
            if not meeting:
                raise SystemExit("Archived meeting not found.")
            meeting.deleted_at = None
            if meeting.status == "processing":
                meeting.status, meeting.lease_until, meeting.lease_token = "queued", None, ""
            service._audit(session, meeting.workspace_id, "operator", "meeting.restored", meeting.id)
        print("Meeting restored.")


if __name__ == "__main__":
    main()
