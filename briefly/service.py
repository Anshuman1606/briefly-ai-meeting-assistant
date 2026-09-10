"""Application boundary: authentication, workspace authorization and durable jobs.

Never trust a role or workspace ID from Streamlit session_state. Only the opaque
session token is accepted, and permissions are re-read on every operation.
"""

import hashlib
import logging
import os
import re
import secrets
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import and_, create_engine, delete, event, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from briefly.models import (
    Action, Audit, AuthSession, Chat, Chunk, Meeting, Membership, RateBucket,
    User, Workspace, now, uid,
)

LOG = logging.getLogger("briefly")
MAX_UPLOAD = 25 * 1024 * 1024
MAX_TRANSCRIPT = 100_000
SAMPLE = """[00:00] Maya: Welcome to the Atlas launch review. Our goal is to launch the customer dashboard on October 15. Today we need to agree on scope and ownership.
[00:38] Arjun: The dashboard is ready for the pilot. We have completed all twelve core reports, but the CSV export still needs testing with large accounts.
[01:12] Maya: We decided to launch with the twelve core reports and move custom report builders to the next release. The October 15 launch date is confirmed.
[01:56] Priya: I will complete the security review by October 10. My review will cover workspace isolation, audit logs, and data export permissions.
[02:33] Arjun: I will fix the CSV export timeout by October 9. The fix is to stream large exports instead of loading them into memory.
[03:15] Leo: I will prepare the customer onboarding guide by October 12. The guide will cover workspace setup and inviting teammates.
[04:02] Maya: We agreed to run a pilot with five customer teams before the public launch. Priya owns the go or no-go security approval.
[04:42] Priya: Do we need a separate data retention policy for enterprise customers? Legal should confirm this before we onboard regulated customers.
[05:10] Leo: Which customer team will be the first pilot participant? We still need a response from the account managers.
[05:44] Maya: I will confirm the five pilot teams by October 8. We will meet again on October 11 to review the remaining risks.
[06:20] Arjun: The main remaining risk is performance for accounts above one million rows. We should monitor the pilot before increasing the rollout.
[06:52] Maya: Thank you. The launch scope, owners, and deadlines are now agreed. Let's track all follow-ups in the shared workspace."""


def _dict(obj, exclude=()):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Service:
    def __init__(self, db_url=None):
        self.production = os.getenv("APP_ENV", "local") == "production"
        self.auth_mode = os.getenv("AUTH_MODE", "password")
        self.signup_allowed = os.getenv("ALLOW_SIGNUP", "false" if self.production else "true").lower() == "true"
        url = db_url or os.getenv("DATABASE_URL", "")
        if self.production and (not url or not url.startswith(("postgresql", "postgres://"))):
            raise ValueError("Production requires an external PostgreSQL DATABASE_URL in Streamlit secrets. Local disk is not durable on Community Cloud.")
        if not url:
            Path("data").mkdir(mode=0o700, exist_ok=True)
            url = "sqlite:///data/briefly.db"
        if url.startswith(("postgres://", "postgresql://")):
            url = "postgresql+psycopg://" + url.split("://", 1)[1]
        kw = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                kw["poolclass"] = StaticPool
        self.engine = create_engine(url, **kw)
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def sqlite_setup(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
        from briefly.schema import ensure_schema
        ensure_schema(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self.passwords = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        self._dummy_hash = self.passwords.hash(secrets.token_urlsafe(32))
        self._worker_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def capabilities(self):
        backend = os.getenv("TRANSCRIPTION_BACKEND", "disabled")
        return {
            "provider_mode": "Mistral · source-grounded analysis" if os.getenv("MISTRAL_API_KEY") else "Extractive · no API key required",
            "transcription_mode": {"disabled": "Disabled · paste text or import captions", "whisper": "Local Whisper", "sarvam": "Sarvam · Hindi / Hinglish WAV"}.get(backend, backend),
            "persistence_mode": "PostgreSQL · external database" if self.engine.dialect.name == "postgresql" else "SQLite · local development storage",
            "audio_enabled": backend != "disabled",
            "signup_allowed": self.signup_allowed,
        }

    def _rate(self, namespace, subject, limit=30, seconds=900):
        moment = now()
        window = int(moment.timestamp()) // seconds
        key = _hash(f"{namespace}:{subject}:{window}")
        insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        with self.Session.begin() as s:
            statement = insert(RateBucket).values(key=key, count=1, expires_at=moment + timedelta(seconds=seconds * 2))
            s.execute(statement.on_conflict_do_update(index_elements=["key"], set_={"count": RateBucket.count + 1}))
            count = s.get(RateBucket, key).count
        if count > limit:
            raise ValueError("Too many requests. Please wait before trying again.")

    def _audit(self, s, workspace_id, actor, action, resource=""):
        s.add(Audit(workspace_id=workspace_id, actor=actor, event=action, resource_id=resource))

    def _identity(self, s, user, roles=None):
        token = user.get("token", "") if isinstance(user, dict) else ""
        auth = s.get(AuthSession, _hash(token)) if token else None
        if auth is None or auth.expires_at <= now():
            raise ValueError("Your session has expired. Please sign in again.")
        member = s.scalar(select(Membership).where(Membership.user_id == auth.user_id, Membership.workspace_id == auth.workspace_id))
        account = s.get(User, auth.user_id)
        if member is None or account is None:
            raise ValueError("You do not have access to this workspace.")
        if roles and member.role not in roles:
            raise ValueError("Your workspace role does not allow this action.")
        return auth, member, account

    def _issue(self, s, account, workspace_id=None):
        query = select(Membership).where(Membership.user_id == account.id)
        if workspace_id:
            query = query.where(Membership.workspace_id == workspace_id)
        member = s.scalar(query)
        if not member:
            raise ValueError("No accessible workspace was found.")
        workspace = s.get(Workspace, member.workspace_id)
        token = secrets.token_urlsafe(48)
        s.add(AuthSession(token_hash=_hash(token), user_id=account.id, workspace_id=workspace.id, expires_at=now() + timedelta(hours=8)))
        return {"id": account.id, "username": account.username, "email": account.email, "workspace_id": workspace.id, "workspace_name": workspace.name, "role": member.role, "token": token}

    def register(self, username, email, password, workspace_name):
        if not self.signup_allowed or self.auth_mode != "password":
            raise ValueError("Self-registration is disabled. Contact your workspace administrator.")
        self._rate("signup", "global", 30, 3600)
        username, email, workspace_name = username.strip().lower(), email.strip().lower(), workspace_name.strip()
        if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
            raise ValueError("Username must be 3–40 lowercase letters, numbers, dots, dashes or underscores.")
        if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Enter a valid email address.")
        if len(password) < 12 or len(password) > 256:
            raise ValueError("Use a password between 12 and 256 characters.")
        if not 2 <= len(workspace_name) <= 100:
            raise ValueError("Workspace name must be 2–100 characters.")
        try:
            with self.Session.begin() as s:
                account = User(username=username, email=email, password_hash=self.passwords.hash(password))
                workspace = Workspace(name=workspace_name)
                s.add_all([account, workspace])
                s.flush()
                s.add(Membership(workspace_id=workspace.id, user_id=account.id, role="owner"))
                s.flush()
                self._audit(s, workspace.id, username, "workspace.created", workspace.id)
                return self._issue(s, account)
        except IntegrityError:
            raise ValueError("This username or email is already registered.") from None

    def login(self, username, password):
        if self.auth_mode != "password":
            raise ValueError("Use your organization's single sign-on.")
        username = username.strip().lower()[:254]
        self._rate("login", username, 10, 900)
        if len(password) > 256:
            raise ValueError("Invalid username or password.")
        with self.Session.begin() as s:
            account = s.scalar(select(User).where(or_(User.username == username, User.email == username)))
            try:
                self.passwords.verify(account.password_hash if account else self._dummy_hash, password)
            except VerificationError:
                raise ValueError("Invalid username or password.") from None
            if account is None:
                raise ValueError("Invalid username or password.")
            if self.passwords.check_needs_rehash(account.password_hash):
                account.password_hash = self.passwords.hash(password)
            result = self._issue(s, account)
            self._audit(s, result["workspace_id"], account.username, "auth.login")
            return result

    def oidc_login(self, claims):
        """Called only with Streamlit's verified st.user; never accept user form claims."""
        if self.auth_mode != "oidc":
            raise ValueError("Single sign-on is not enabled.")
        email = str(claims.get("email", "")).strip().lower()
        domains = {x.strip().lower() for x in os.getenv("OIDC_ALLOWED_DOMAINS", "").split(",") if x.strip()}
        if claims.get("email_verified") is not True or not domains or email.rsplit("@", 1)[-1] not in domains:
            raise ValueError("A verified email from an approved organization is required.")
        subject = str(claims.get("sub", ""))
        issuer = str(claims.get("iss", ""))
        if not subject or not issuer:
            raise ValueError("The identity provider did not return a valid subject and issuer.")
        username = "sso_" + _hash(issuer + ":" + subject)[:32]
        with self.Session.begin() as s:
            account = s.scalar(select(User).where(User.username == username))
            if not account:
                if s.scalar(select(User).where(User.email == email)):
                    raise ValueError("This email belongs to another login. Ask an administrator to migrate the account.")
                account = User(username=username, email=email, password_hash=self.passwords.hash(secrets.token_urlsafe(48)))
                workspace = Workspace(name=str(claims.get("name", email.split("@")[0]))[:80] + "'s workspace")
                s.add_all([account, workspace])
                s.flush()
                s.add(Membership(user_id=account.id, workspace_id=workspace.id, role="owner"))
                s.flush()
            return self._issue(s, account)

    def demo_login(self):
        if self.production:
            raise ValueError("Demo sessions are disabled in production.")
        suffix = secrets.token_hex(8)
        with self.Session.begin() as s:
            account = User(username=f"demo_{suffix}", email=f"demo_{suffix}@example.invalid", password_hash=self._dummy_hash)
            workspace = Workspace(name="Atlas · private demo")
            s.add_all([account, workspace])
            s.flush()
            s.add(Membership(user_id=account.id, workspace_id=workspace.id, role="owner"))
            s.flush()
            result = self._issue(s, account)
        result["demo"] = True
        self.sample_meeting(result)
        return result

    def logout(self, user):
        with self.Session.begin() as s:
            s.execute(delete(AuthSession).where(AuthSession.token_hash == _hash(user.get("token", ""))))

    def workspaces(self, user):
        with self.Session() as s:
            auth, _, _ = self._identity(s, user)
            rows = s.execute(select(Workspace, Membership).join(Membership).where(Membership.user_id == auth.user_id)).all()
            return [{"id": w.id, "name": w.name, "role": m.role} for w, m in rows]

    def switch_workspace(self, user, workspace_id):
        with self.Session.begin() as s:
            auth, _, account = self._identity(s, user)
            result = self._issue(s, account, workspace_id)
            s.delete(auth)
            return result

    def _meeting(self, s, user, meeting_id, roles=None):
        _, member, account = self._identity(s, user, roles)
        meeting = s.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.workspace_id == member.workspace_id, Meeting.deleted_at.is_(None)))
        if meeting is None:
            raise ValueError("Meeting not found in this workspace.")
        return meeting, member, account

    def list_meetings(self, user, q="", status=""):
        with self.Session() as s:
            _, member, _ = self._identity(s, user)
            query = select(Meeting).where(Meeting.workspace_id == member.workspace_id, Meeting.deleted_at.is_(None))
            if q:
                query = query.where(Meeting.title.ilike("%" + q[:160].replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
            if status in {"queued", "processing", "ready", "failed"}:
                query = query.where(Meeting.status == status)
            return [_dict(x, ("upload", "lease_token", "transcript")) for x in s.scalars(query.order_by(Meeting.created_at.desc()).limit(500))]

    def get_meeting(self, user, meeting_id):
        with self.Session() as s:
            meeting, _, _ = self._meeting(s, user, meeting_id)
            result = _dict(meeting, ("upload", "lease_token"))
            result["chunks"] = [_dict(x) for x in s.scalars(select(Chunk).where(Chunk.meeting_id == meeting.id).order_by(Chunk.index))]
            result["actions"] = [_dict(x) for x in s.scalars(select(Action).where(Action.meeting_id == meeting.id))]
            result["chats"] = [_dict(x) for x in s.scalars(select(Chat).where(Chat.meeting_id == meeting.id).order_by(Chat.created_at).limit(200))]
            return result

    def create_meeting(self, user, title, source_type, transcript="", source_url="", file_bytes=None, filename="", language="auto"):
        from briefly.intelligence import validate_youtube_url
        title = title.strip()
        if not title or len(title) > 160:
            raise ValueError("Meeting title must be 1–160 characters.")
        if source_type not in {"transcript", "youtube", "audio", "video"}:
            raise ValueError("Choose a supported source type.")
        if language not in {"auto", "en", "hi", "hinglish"}:
            raise ValueError("Choose English, Hindi, Hinglish, or automatic language detection.")
        filename = Path(filename).name[:180]
        if source_type == "transcript":
            transcript = transcript.strip()
            if not 40 <= len(transcript) <= MAX_TRANSCRIPT:
                raise ValueError("Paste a transcript between 40 and 100,000 characters.")
            source_url, file_bytes = "", None
        elif source_type == "youtube":
            source_url = validate_youtube_url(source_url)
            transcript, file_bytes = "", None
        else:
            if os.getenv("TRANSCRIPTION_BACKEND", "disabled") == "disabled":
                raise ValueError("Audio transcription is not configured. Paste a transcript or configure a transcription provider in server secrets.")
            if not file_bytes or len(file_bytes) > MAX_UPLOAD:
                raise ValueError("Upload a non-empty file up to 25 MB.")
            if Path(filename).suffix.lower() not in {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac"}:
                raise ValueError("Unsupported media format.")
            transcript, source_url = "", ""
        with self.Session.begin() as s:
            _, member, account = self._identity(s, user, {"owner", "editor"})
            self._rate("ingest", member.workspace_id, 30, 3600)
            # Serialize quota check and insertion across workers on PostgreSQL.
            s.scalar(select(Workspace).where(Workspace.id == member.workspace_id).with_for_update())
            count = s.scalar(select(func.count()).select_from(Meeting).where(Meeting.workspace_id == member.workspace_id))
            if count >= 500:
                raise ValueError("This workspace has reached its 500-meeting limit. Contact the operator about retention.")
            meeting = Meeting(title=title, workspace_id=member.workspace_id, created_by=account.id, source_type=source_type, transcript=transcript, source_url=source_url, upload=file_bytes, filename=filename, language=language)
            s.add(meeting)
            s.flush()
            self._audit(s, member.workspace_id, account.username, "meeting.created", meeting.id)
            return meeting.id

    def sample_meeting(self, user):
        return self.create_meeting(user, "Atlas launch · scope, owners & next steps", "transcript", SAMPLE, language="en")

    def retry_meeting(self, user, meeting_id):
        with self.Session.begin() as s:
            meeting, member, account = self._meeting(s, user, meeting_id, {"owner", "editor"})
            if meeting.status != "failed":
                raise ValueError("Only failed meetings can be retried.")
            self._rate("retry", meeting.id, 5, 3600)
            meeting.status, meeting.error, meeting.attempts = "queued", "", 0
            self._audit(s, member.workspace_id, account.username, "meeting.retried", meeting.id)

    def delete_meeting(self, user, meeting_id):
        """Archive for 30-day operator recovery; maintenance later purges data."""
        with self.Session.begin() as s:
            meeting, member, account = self._meeting(s, user, meeting_id, {"owner"})
            meeting.deleted_at = now()
            meeting.lease_token = ""
            self._audit(s, member.workspace_id, account.username, "meeting.archived", meeting.id)

    def ask(self, user, meeting_id, question):
        from briefly.intelligence import answer_question
        question = question.strip()
        if not 3 <= len(question) <= 1000:
            raise ValueError("Ask a question between 3 and 1,000 characters.")
        with self.Session() as s:
            meeting, member, _ = self._meeting(s, user, meeting_id)
            if meeting.status != "ready":
                raise ValueError("Wait for processing to complete before asking questions.")
            count = s.scalar(select(func.count()).select_from(Chat).where(Chat.meeting_id == meeting_id))
            if count >= 200:
                raise ValueError("This meeting has reached its 200-question history limit.")
            self._rate("chat", member.workspace_id, 60, 3600)
            chunks = [_dict(x) for x in s.scalars(select(Chunk).where(Chunk.meeting_id == meeting.id).order_by(Chunk.index))]
        answer = answer_question(question, chunks)
        with self.Session.begin() as s:
            meeting, member, account = self._meeting(s, user, meeting_id)
            s.scalar(select(Meeting).where(Meeting.id == meeting_id).with_for_update())
            count = s.scalar(select(func.count()).select_from(Chat).where(Chat.meeting_id == meeting_id))
            if count >= 200:
                raise ValueError("This meeting has reached its 200-question history limit.")
            s.add(Chat(meeting_id=meeting.id, user_id=account.id, question=question, answer=answer["answer"], citations=answer["citations"], mode=answer["mode"]))
            self._audit(s, member.workspace_id, account.username, "meeting.question_answered", meeting.id)
        return answer

    def list_actions(self, user):
        with self.Session() as s:
            _, member, _ = self._identity(s, user)
            rows = s.execute(select(Action, Meeting.title).join(Meeting).where(Meeting.workspace_id == member.workspace_id, Meeting.deleted_at.is_(None)).order_by(Action.status, Meeting.created_at.desc()).limit(1000)).all()
            return [{**_dict(action), "meeting_title": title} for action, title in rows]

    def toggle_action(self, user, action_id):
        with self.Session.begin() as s:
            _, member, account = self._identity(s, user, {"owner", "editor"})
            action = s.scalar(select(Action).join(Meeting).where(Action.id == action_id, Meeting.workspace_id == member.workspace_id, Meeting.deleted_at.is_(None)).with_for_update())
            if action is None:
                raise ValueError("Action not found in this workspace.")
            action.status = "done" if action.status == "open" else "open"
            self._audit(s, member.workspace_id, account.username, "action." + action.status, action.id)

    def members(self, user):
        with self.Session() as s:
            _, member, _ = self._identity(s, user)
            rows = s.execute(select(Membership, User).join(User).where(Membership.workspace_id == member.workspace_id)).all()
            return [{"id": m.id, "username": u.username, "email": u.email, "role": m.role} for m, u in rows]

    def add_member(self, user, email, role):
        if role not in {"editor", "viewer"}:
            raise ValueError("New members can be editors or viewers.")
        with self.Session.begin() as s:
            _, member, account = self._identity(s, user, {"owner"})
            self._rate("members", member.workspace_id, 30, 3600)
            # Unverified password registrations cannot receive invitations by email.
            if self.production and self.auth_mode != "oidc":
                raise ValueError("Enable verified organization SSO before adding production team members.")
            target = s.scalar(select(User).where(User.email == email.strip().lower()))
            if not target:
                raise ValueError("Ask this person to sign in first, then add their registered email.")
            existing = s.scalar(select(Membership).where(Membership.workspace_id == member.workspace_id, Membership.user_id == target.id))
            if existing and existing.role == "owner":
                raise ValueError("The owner role cannot be changed here.")
            if existing:
                existing.role = role
            else:
                s.add(Membership(workspace_id=member.workspace_id, user_id=target.id, role=role))
            self._audit(s, member.workspace_id, account.username, "member." + role, target.id)

    def remove_member(self, user, member_id):
        with self.Session.begin() as s:
            _, member, account = self._identity(s, user, {"owner"})
            target = s.scalar(select(Membership).where(Membership.id == member_id, Membership.workspace_id == member.workspace_id))
            if not target or target.role == "owner":
                raise ValueError("Only non-owner members can be removed.")
            s.execute(delete(AuthSession).where(AuthSession.user_id == target.user_id, AuthSession.workspace_id == member.workspace_id))
            self._audit(s, member.workspace_id, account.username, "member.removed", target.user_id)
            s.delete(target)

    def audit(self, user):
        with self.Session() as s:
            _, member, _ = self._identity(s, user, {"owner"})
            return [_dict(x) for x in s.scalars(select(Audit).where(Audit.workspace_id == member.workspace_id).order_by(Audit.created_at.desc()).limit(500))]

    def export_meeting(self, user, meeting_id, fmt):
        from briefly.exports import export_report
        report = self.get_meeting(user, meeting_id)
        if report["status"] != "ready":
            raise ValueError("Only processed meetings can be exported.")
        result = export_report(report, fmt)
        with self.Session.begin() as s:
            _, member, account = self._meeting(s, user, meeting_id)
            self._audit(s, member.workspace_id, account.username, "meeting.exported_" + fmt, meeting_id)
        return result

    def start_worker(self):
        if os.getenv("BRIEFLY_EMBEDDED_WORKER", "true").lower() != "true":
            return
        with self._worker_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self.run_worker, name="briefly-worker", daemon=True)
            self._thread.start()

    def stop_worker(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def run_worker(self):
        while not self._stop.is_set():
            try:
                if self.process_next():
                    continue
            except Exception:
                LOG.error("worker_cycle_failed")
            self._stop.wait(2)

    def _heartbeat(self, meeting_id, token, done):
        while not done.wait(20):
            try:
                with self.Session.begin() as s:
                    s.execute(update(Meeting).where(Meeting.id == meeting_id, Meeting.lease_token == token, Meeting.deleted_at.is_(None)).values(lease_until=now() + timedelta(minutes=3)))
            except Exception:
                LOG.error("job_heartbeat_failed meeting_id=%s", meeting_id)

    def process_next(self):
        from briefly.intelligence import IntelligenceError, analyze_transcript, fetch_youtube_transcript, split_transcript, transcribe_file
        token = uid()
        eligible = and_(Meeting.deleted_at.is_(None), or_(Meeting.status == "queued", and_(Meeting.status == "processing", Meeting.lease_until < now())))
        with self.Session.begin() as s:
            query = select(Meeting).where(eligible).order_by(Meeting.created_at).limit(1)
            if self.engine.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            meeting = s.scalar(query)
            if meeting is None:
                return False
            meeting_id = meeting.id
            result = s.execute(update(Meeting).where(Meeting.id == meeting_id, eligible).values(status="processing", lease_token=token, lease_until=now() + timedelta(minutes=3), attempts=Meeting.attempts + 1))
            if result.rowcount != 1:
                return False
            s.refresh(meeting)
            source = _dict(meeting)
        done = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(meeting_id, token, done), daemon=True)
        heartbeat.start()
        try:
            if source["attempts"] > 3:
                raise IntelligenceError("Processing was interrupted three times. Retry after checking the worker resources.")
            transcript = source["transcript"]
            if not transcript:
                if source["source_type"] == "youtube":
                    transcript = fetch_youtube_transcript(source["source_url"])
                else:
                    suffix = Path(source["filename"]).suffix.lower()
                    with tempfile.TemporaryDirectory(prefix="briefly-") as temp:
                        path = Path(temp) / ("source" + suffix)
                        path.write_bytes(source["upload"] or b"")
                        transcript = transcribe_file(str(path), source["language"])
                if len(transcript) > MAX_TRANSCRIPT:
                    raise IntelligenceError("Transcript exceeds the 100,000-character limit. Split the recording and retry.")
                # Preserve transcription before inference so a provider retry need not retranscribe.
                with self.Session.begin() as s:
                    s.execute(update(Meeting).where(Meeting.id == meeting_id, Meeting.lease_token == token, Meeting.deleted_at.is_(None)).values(transcript=transcript, upload=None))
            analysis = analyze_transcript(transcript)
            chunks = split_transcript(transcript)
            with self.Session.begin() as s:
                target = s.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.lease_token == token, Meeting.deleted_at.is_(None)).with_for_update())
                if target is None:
                    return True
                s.execute(delete(Chunk).where(Chunk.meeting_id == meeting_id))
                s.execute(delete(Action).where(Action.meeting_id == meeting_id))
                for chunk in chunks:
                    s.add(Chunk(meeting_id=meeting_id, index=chunk["index"], text=chunk["text"], start=chunk.get("start")))
                for action in analysis.get("actions", []):
                    s.add(Action(meeting_id=meeting_id, text=action["text"], owner=str(action.get("owner") or "Unassigned")[:120], deadline=str(action.get("deadline") or "Not specified")[:120], evidence=action.get("evidence", "")))
                target.transcript = transcript
                target.upload = None
                target.summary = analysis["summary"]
                target.decisions = analysis.get("decisions", [])
                target.questions = analysis.get("questions", [])
                target.analysis_mode = analysis["mode"]
                target.duration_seconds = int(max((x.get("start") or 0 for x in chunks), default=0))
                target.status, target.error, target.lease_token, target.lease_until = "ready", "", "", None
                self._audit(s, target.workspace_id, "worker", "meeting.processed", meeting_id)
            LOG.info("job_completed meeting_id=%s mode=%s", meeting_id, analysis["mode"])
        except Exception as exc:
            safe_error = str(exc)[:600] if isinstance(exc, IntelligenceError) else "Processing failed. Check the provider configuration and worker logs, then retry."
            with self.Session.begin() as s:
                s.execute(update(Meeting).where(Meeting.id == meeting_id, Meeting.lease_token == token, Meeting.deleted_at.is_(None)).values(status="failed", error=safe_error, lease_token="", lease_until=None))
            LOG.warning("job_failed meeting_id=%s error_type=%s", meeting_id, type(exc).__name__)
        finally:
            done.set()
            heartbeat.join(timeout=1)
        return True

    def maintenance(self, retention_days=30):
        if retention_days < 1:
            raise ValueError("Retention must be at least one day.")
        with self.Session.begin() as s:
            s.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
            s.execute(delete(RateBucket).where(RateBucket.expires_at < now()))
            old = list(s.scalars(select(Meeting.id).where(Meeting.deleted_at < now() - timedelta(days=retention_days))))
            for table in (Chat, Action, Chunk):
                s.execute(delete(table).where(table.meeting_id.in_(old)))
            s.execute(delete(Meeting).where(Meeting.id.in_(old)))
        return len(old)
