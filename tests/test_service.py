"""Service-boundary checks with a real file database and no provider network calls."""

import copy
from datetime import timedelta
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from alembic.migration import MigrationContext
from sqlalchemy import func, select

from briefly.models import Action, AuthSession, Chat, Chunk, Meeting, now
from briefly.service import MAX_TRANSCRIPT_BYTES, Service


TEXT = "[00:00] Maya: We agreed to ship the dashboard.\n[00:30] Arjun: I will test exports by Friday."
ANALYSIS = {
    "summary": ["The team agreed to ship the dashboard."],
    "decisions": ["Ship the dashboard."],
    "questions": [],
    "actions": [{"text": "Test exports", "owner": "Arjun", "deadline": "Friday", "evidence": "I will test exports by Friday."}],
    "mode": "extractive",
}
CHUNKS = [{"index": 0, "text": "We agreed to ship the dashboard.", "start": 0.0},
          {"index": 1, "text": "I will test exports by Friday.", "start": 30.0}]
ANSWER = {"answer": "Arjun will test exports.", "citations": [{"index": 1, "text": "I will test exports by Friday."}], "mode": "extractive"}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "APP_ENV": "local", "AUTH_MODE": "password", "ALLOW_SIGNUP": "true",
            "TRANSCRIPTION_BACKEND": "disabled", "BRIEFLY_EMBEDDED_WORKER": "false",
            "MISTRAL_API_KEY": "", "OIDC_ALLOWED_DOMAINS": "",
        })
        self.env.start()
        self.temp = tempfile.TemporaryDirectory(prefix="briefly-service-test-")
        self.url = "sqlite:///" + str(Path(self.temp.name) / "test.db")
        self.service = Service(self.url)
        self.owner = self.service.register("alice", "alice@example.test", "VeryStrongPassword!42", "Alice team")
        self.other = self.service.register("bob", "bob@example.test", "AnotherStrongPassword!42", "Bob team")

    def tearDown(self):
        self.service.stop_worker()
        self.service.engine.dispose()
        self.temp.cleanup()
        self.env.stop()

    def create(self, user=None, **kwargs):
        return self.service.create_meeting(user or self.owner, "Launch review", "transcript", kwargs.pop("transcript", TEXT), **kwargs)

    def process(self, analysis=None):
        with patch("briefly.intelligence.analyze_transcript", return_value=copy.deepcopy(analysis or ANALYSIS)), patch("briefly.intelligence.split_transcript", return_value=copy.deepcopy(CHUNKS)):
            return self.service.process_next()

    def ready(self):
        meeting_id = self.create()
        self.assertTrue(self.process())
        return meeting_id

    def viewer(self):
        self.service.add_member(self.owner, self.other["email"], "viewer")
        return self.service.switch_workspace(self.other, self.owner["workspace_id"])

    def test_startup_uses_versioned_migrations(self):
        with self.service.engine.connect() as connection:
            self.assertEqual(("0001_initial",), MigrationContext.configure(connection).get_current_heads())

    def test_tenant_read_chat_action_and_export_isolation(self):
        meeting_id = self.ready()
        own = self.service.get_meeting(self.owner, meeting_id)
        action_id = own["actions"][0]["id"]
        self.assertEqual([], self.service.list_meetings(self.other))
        self.assertEqual([], self.service.list_actions(self.other))
        exporter = Mock(return_value=(b"unused", "text/plain", "unused.txt"))
        with patch("briefly.intelligence.answer_question") as provider, patch.dict("sys.modules", {"briefly.exports": SimpleNamespace(export_report=exporter)}):
            for operation in (
                lambda: self.service.get_meeting(self.other, meeting_id),
                lambda: self.service.ask(self.other, meeting_id, "Who owns the export task?"),
                lambda: self.service.toggle_action(self.other, action_id),
                lambda: self.service.export_meeting(self.other, meeting_id, "markdown"),
                lambda: self.service.retry_meeting(self.other, meeting_id),
                lambda: self.service.delete_meeting(self.other, meeting_id),
            ):
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    operation()
            provider.assert_not_called()
            exporter.assert_not_called()
        self.assertEqual("open", self.service.get_meeting(self.owner, meeting_id)["actions"][0]["status"])
        self.assertEqual([], self.service.get_meeting(self.owner, meeting_id)["chats"])

    def test_forged_identity_fields_do_not_switch_tenant(self):
        meeting_id = self.ready()
        forged = {**self.other, "id": self.owner["id"], "workspace_id": self.owner["workspace_id"], "role": "owner", "username": "alice"}
        with self.assertRaises(ValueError):
            self.service.get_meeting(forged, meeting_id)
        self.assertEqual([], self.service.list_meetings(forged))

    def test_viewer_cannot_escalate_via_forged_role(self):
        meeting_id = self.ready()
        action_id = self.service.get_meeting(self.owner, meeting_id)["actions"][0]["id"]
        viewer = self.viewer()
        forged = {**viewer, "role": "owner", "id": self.owner["id"]}
        self.assertEqual(meeting_id, self.service.get_meeting(viewer, meeting_id)["id"])
        for operation in (
            lambda: self.create(forged),
            lambda: self.service.toggle_action(forged, action_id),
            lambda: self.service.delete_meeting(forged, meeting_id),
            lambda: self.service.retry_meeting(forged, meeting_id),
            lambda: self.service.add_member(forged, self.owner["email"], "editor"),
            lambda: self.service.audit(forged),
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "role"):
                operation()

    def test_role_downgrade_applies_to_existing_session(self):
        self.service.add_member(self.owner, self.other["email"], "editor")
        editor = self.service.switch_workspace(self.other, self.owner["workspace_id"])
        self.create(editor)
        self.service.add_member(self.owner, self.other["email"], "viewer")
        self.assertEqual("editor", editor["role"], "The stale UI identity intentionally still says editor")
        with self.assertRaisesRegex(ValueError, "role"):
            self.create(editor)

    def test_member_removal_revokes_existing_workspace_session(self):
        viewer = self.viewer()
        member = next(x for x in self.service.members(self.owner) if x["email"] == self.other["email"])
        self.service.remove_member(self.owner, member["id"])
        with self.assertRaises(ValueError):
            self.service.list_meetings(viewer)

    def test_logout_expiry_and_token_storage(self):
        with self.service.Session() as session:
            rows = list(session.scalars(select(AuthSession)))
            self.assertNotIn(self.owner["token"], [x.token_hash for x in rows])
            self.assertIn(hashlib.sha256(self.owner["token"].encode()).hexdigest(), [x.token_hash for x in rows])
        self.service.logout(self.owner)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.service.list_meetings(self.owner)
        with self.service.Session.begin() as session:
            auth = session.get(AuthSession, hashlib.sha256(self.other["token"].encode()).hexdigest())
            auth.expires_at = now() - timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.service.list_meetings(self.other)

    def test_workspace_switch_rotates_and_revokes_old_token(self):
        with self.assertRaises(ValueError):
            self.service.switch_workspace(self.other, self.owner["workspace_id"])
        self.service.add_member(self.owner, self.other["email"], "viewer")
        switched = self.service.switch_workspace(self.other, self.owner["workspace_id"])
        self.assertNotEqual(self.other["token"], switched["token"])
        with self.assertRaises(ValueError):
            self.service.workspaces(self.other)
        self.assertEqual(2, len(self.service.workspaces(switched)))

    def test_login_rejects_wrong_password_and_accepts_email(self):
        with self.assertRaisesRegex(ValueError, "Invalid username or password"):
            self.service.login("alice", "incorrect-password")
        logged_in = self.service.login("ALICE@EXAMPLE.TEST", "VeryStrongPassword!42")
        self.assertEqual(self.owner["id"], logged_in["id"])
        self.assertNotEqual(self.owner["token"], logged_in["token"])

    def test_ask_persists_grounded_response_and_rechecks_revocation(self):
        meeting_id = self.ready()
        with patch("briefly.intelligence.answer_question", return_value=copy.deepcopy(ANSWER)):
            result = self.service.ask(self.owner, meeting_id, "Who owns the export task?")
        self.assertEqual(ANSWER, result)
        self.assertEqual(1, len(self.service.get_meeting(self.owner, meeting_id)["chats"]))

        def revoke_during_provider(*_):
            self.service.logout(self.owner)
            return copy.deepcopy(ANSWER)

        with patch("briefly.intelligence.answer_question", side_effect=revoke_during_provider), self.assertRaises(ValueError):
            self.service.ask(self.owner, meeting_id, "Who owns the export task?")
        with self.service.Session() as session:
            self.assertEqual(1, session.scalar(select(func.count()).select_from(Chat)))

    def test_export_uses_authorized_report_and_records_audit(self):
        meeting_id = self.ready()
        expected = (b"report", "text/markdown", "report.md")
        exporter = Mock(return_value=expected)
        with patch.dict("sys.modules", {"briefly.exports": SimpleNamespace(export_report=exporter)}):
            self.assertEqual(expected, self.service.export_meeting(self.owner, meeting_id, "markdown"))
        self.assertEqual(meeting_id, exporter.call_args.args[0]["id"])
        self.assertTrue(any(x["event"] == "meeting.exported_markdown" for x in self.service.audit(self.owner)))

    def test_export_rechecks_archive_state_before_returning_data(self):
        meeting_id = self.ready()

        def archive_during_export(*_):
            self.service.delete_meeting(self.owner, meeting_id)
            return b"archived report", "text/markdown", "report.md"

        exporter = Mock(side_effect=archive_during_export)
        with patch.dict("sys.modules", {"briefly.exports": SimpleNamespace(export_report=exporter)}), self.assertRaises(ValueError):
            self.service.export_meeting(self.owner, meeting_id, "markdown")
        self.assertFalse(any(x["event"] == "meeting.exported_markdown" for x in self.service.audit(self.owner)))

    def test_full_chat_history_does_not_call_provider(self):
        meeting_id = self.ready()
        with self.service.Session.begin() as session:
            session.add_all(Chat(meeting_id=meeting_id, user_id=self.owner["id"], question=f"Question {i}", answer="Answer", citations=[], mode="extractive") for i in range(200))
        with patch("briefly.intelligence.answer_question", return_value=copy.deepcopy(ANSWER)) as provider:
            with self.assertRaisesRegex(ValueError, "200-question"):
                self.service.ask(self.owner, meeting_id, "Who owns the export task?")
            provider.assert_not_called()

    def test_ready_job_is_not_processed_twice(self):
        meeting_id = self.ready()
        with patch("briefly.intelligence.analyze_transcript") as analyze:
            self.assertFalse(self.service.process_next())
            analyze.assert_not_called()
        report = self.service.get_meeting(self.owner, meeting_id)
        self.assertEqual("ready", report["status"])
        self.assertEqual(1, report["attempts"])
        self.assertEqual(1, len(report["actions"]))
        self.assertEqual(2, len(report["chunks"]))

    def test_failure_is_sanitized_and_explicit_retry_succeeds(self):
        meeting_id = self.create()
        with patch("briefly.intelligence.analyze_transcript", side_effect=RuntimeError("secret-provider-token-should-never-leak")):
            self.assertTrue(self.service.process_next())
        report = self.service.get_meeting(self.owner, meeting_id)
        self.assertEqual("failed", report["status"])
        self.assertNotIn("secret-provider-token", report["error"])
        self.assertFalse(self.process(), "Failed work must not create an unbounded automatic retry loop")
        self.service.retry_meeting(self.owner, meeting_id)
        self.assertTrue(self.process())
        report = self.service.get_meeting(self.owner, meeting_id)
        self.assertEqual("ready", report["status"])
        self.assertEqual("", report["error"])
        self.assertEqual(1, len(report["actions"]))

    def test_unclassified_value_errors_never_expose_raw_exception_details(self):
        meeting_id = self.create()
        with patch("briefly.intelligence.analyze_transcript", side_effect=ValueError("secret-provider-token-should-never-leak")):
            self.assertTrue(self.service.process_next())
        report = self.service.get_meeting(self.owner, meeting_id)
        self.assertEqual("failed", report["status"])
        self.assertNotIn("secret-provider-token", report["error"])

    def test_known_safe_processing_errors_remain_actionable(self):
        from briefly.intelligence import IntelligenceError
        meeting_id = self.create()
        with patch("briefly.intelligence.analyze_transcript", side_effect=IntelligenceError("The AI provider could not process this request. Check its configuration and retry.")):
            self.assertTrue(self.service.process_next())
        self.assertIn("Check its configuration", self.service.get_meeting(self.owner, meeting_id)["error"])

    def test_transcription_survives_analysis_failure_and_retry(self):
        with patch.dict(os.environ, {"TRANSCRIPTION_BACKEND": "sarvam"}):
            meeting_id = self.service.create_meeting(self.owner, "Audio", "audio", file_bytes=b"test bytes", filename="meeting.wav")
        with patch("briefly.intelligence.transcribe_file", return_value=TEXT) as transcribe, patch("briefly.intelligence.analyze_transcript", side_effect=RuntimeError("provider down")):
            self.assertTrue(self.service.process_next())
            transcribe.assert_called_once()
        with self.service.Session() as session:
            meeting = session.get(Meeting, meeting_id)
            self.assertEqual(TEXT, meeting.transcript)
            self.assertIsNone(meeting.upload)
        self.service.retry_meeting(self.owner, meeting_id)
        with patch("briefly.intelligence.transcribe_file") as transcribe:
            self.assertTrue(self.process())
            transcribe.assert_not_called()

    def test_expired_lease_is_reclaimed_without_duplicate_outputs(self):
        meeting_id = self.ready()
        with self.service.Session.begin() as session:
            meeting = session.get(Meeting, meeting_id)
            meeting.status = "processing"
            meeting.lease_token = "abandoned-worker"
            meeting.lease_until = now() - timedelta(seconds=1)
        self.assertTrue(self.process())
        report = self.service.get_meeting(self.owner, meeting_id)
        self.assertEqual("ready", report["status"])
        self.assertEqual(2, report["attempts"])
        self.assertEqual(1, len(report["actions"]))
        self.assertEqual(2, len(report["chunks"]))

    def test_active_lease_is_not_stolen(self):
        meeting_id = self.create()
        with self.service.Session.begin() as session:
            meeting = session.get(Meeting, meeting_id)
            meeting.status, meeting.lease_token = "processing", "live-worker"
            meeting.lease_until = now() + timedelta(minutes=1)
        with patch("briefly.intelligence.analyze_transcript") as analyze:
            self.assertFalse(self.service.process_next())
            analyze.assert_not_called()

    def test_stale_worker_cannot_overwrite_new_lease(self):
        meeting_id = self.create()

        def replace_lease(_):
            with self.service.Session.begin() as session:
                meeting = session.get(Meeting, meeting_id)
                meeting.lease_token = "replacement-worker"
                meeting.summary = ["A replacement owns this record"]
            return copy.deepcopy(ANALYSIS)

        with patch("briefly.intelligence.analyze_transcript", side_effect=replace_lease), patch("briefly.intelligence.split_transcript", return_value=copy.deepcopy(CHUNKS)):
            self.assertTrue(self.service.process_next())
        report = self.service.get_meeting(self.owner, meeting_id)
        self.assertEqual("processing", report["status"])
        self.assertEqual(["A replacement owns this record"], report["summary"])
        self.assertEqual([], report["actions"])

    def test_repeated_crash_recovery_stops_after_attempt_budget(self):
        meeting_id = self.create()
        with self.service.Session.begin() as session:
            meeting = session.get(Meeting, meeting_id)
            meeting.status, meeting.attempts = "processing", 3
            meeting.lease_token, meeting.lease_until = "crashed", now() - timedelta(seconds=1)
        with patch("briefly.intelligence.analyze_transcript") as analyze:
            self.assertTrue(self.service.process_next())
            analyze.assert_not_called()
        self.assertEqual("failed", self.service.get_meeting(self.owner, meeting_id)["status"])

    def test_completed_data_and_queued_work_survive_service_restart(self):
        ready_id = self.ready()
        queued_id = self.create()
        self.service.engine.dispose()
        self.service = Service(self.url)
        report = self.service.get_meeting(self.owner, ready_id)
        self.assertEqual("ready", report["status"])
        self.assertEqual(TEXT, report["transcript"])
        self.assertEqual(ANALYSIS["summary"], report["summary"])
        self.assertTrue(self.process())
        self.assertEqual("ready", self.service.get_meeting(self.owner, queued_id)["status"])

    def test_archived_job_is_invisible_and_not_processed(self):
        meeting_id = self.create()
        self.service.delete_meeting(self.owner, meeting_id)
        self.assertFalse(self.process())
        self.assertEqual([], self.service.list_meetings(self.owner))
        with self.assertRaises(ValueError):
            self.service.get_meeting(self.owner, meeting_id)

    def test_archive_during_processing_prevents_worker_output_commit(self):
        meeting_id = self.create()

        def archive_during_analysis(_):
            self.service.delete_meeting(self.owner, meeting_id)
            return copy.deepcopy(ANALYSIS)

        with patch("briefly.intelligence.analyze_transcript", side_effect=archive_during_analysis), patch("briefly.intelligence.split_transcript", return_value=copy.deepcopy(CHUNKS)):
            self.assertTrue(self.service.process_next())
        with self.service.Session() as session:
            self.assertEqual(0, session.scalar(select(func.count()).select_from(Action)))
            self.assertEqual(0, session.scalar(select(func.count()).select_from(Chunk)))
            self.assertEqual([], session.get(Meeting, meeting_id).summary)
        self.assertEqual([], self.service.list_meetings(self.owner))

    def test_retention_purge_removes_dependent_records(self):
        meeting_id = self.ready()
        with patch("briefly.intelligence.answer_question", return_value=copy.deepcopy(ANSWER)):
            self.service.ask(self.owner, meeting_id, "Who owns the export task?")
        self.service.delete_meeting(self.owner, meeting_id)
        with self.service.Session.begin() as session:
            session.get(Meeting, meeting_id).deleted_at = now() - timedelta(days=31)
        self.assertEqual(1, self.service.maintenance(30))
        with self.service.Session() as session:
            for table in (Meeting, Action, Chunk, Chat):
                self.assertEqual(0, session.scalar(select(func.count()).select_from(table)))

    def test_source_validation_rejects_bad_or_oversized_inputs(self):
        invalid = [
            {"title": "", "source_type": "transcript", "transcript": TEXT},
            {"title": "x" * 161, "source_type": "transcript", "transcript": TEXT},
            {"title": "Meeting", "source_type": "arbitrary", "transcript": TEXT},
            {"title": "Meeting", "source_type": "transcript", "transcript": "too short"},
            {"title": "Meeting", "source_type": "transcript", "transcript": "x" * (MAX_TRANSCRIPT_BYTES + 1)},
            {"title": "Meeting", "source_type": "transcript", "transcript": TEXT, "language": "invalid"},
            {"title": "Meeting", "source_type": "youtube", "source_url": "http://127.0.0.1/admin"},
            {"title": "Meeting", "source_type": "youtube", "source_url": "https://youtube.com.evil.example/watch?v=xlYJhtL0qbQ"},
            {"title": "Meeting", "source_type": "audio", "file_bytes": b"wave", "filename": "meeting.wav"},
        ]
        for kwargs in invalid:
            with self.subTest(source_type=kwargs["source_type"]), self.assertRaises(ValueError):
                self.service.create_meeting(self.owner, **kwargs)
        self.assertEqual([], self.service.list_meetings(self.owner))

    def test_ingestion_counts_utf8_bytes(self):
        with patch("briefly.service.MAX_TRANSCRIPT_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                self.service.create_meeting(self.owner, "Hindi", "transcript", transcript="ह" * 41)
            self.service.create_meeting(self.owner, "English", "transcript", transcript="a" * 60)

    def test_upload_bound_and_filename_sanitization(self):
        with patch.dict(os.environ, {"TRANSCRIPTION_BACKEND": "sarvam"}), patch("briefly.service.MAX_UPLOAD", 25 * 1024 * 1024):
            for data, filename in [(b"", "meeting.wav"), (b"x", "meeting.exe"), (b"x" * (25 * 1024 * 1024 + 1), "meeting.wav")]:
                with self.subTest(filename=filename, size=len(data)), self.assertRaises(ValueError):
                    self.service.create_meeting(self.owner, "Audio", "audio", file_bytes=data, filename=filename)
            meeting_id = self.service.create_meeting(self.owner, "Audio", "audio", file_bytes=b"wave", filename="../../private/meeting.wav")
        self.assertEqual("meeting.wav", self.service.get_meeting(self.owner, meeting_id)["filename"])

    def test_hourly_ingestion_quota_is_workspace_scoped(self):
        for _ in range(30):
            self.create()
        with self.assertRaisesRegex(ValueError, "Too many requests"):
            self.create()
        self.assertEqual(30, len(self.service.list_meetings(self.owner)))
        self.create(self.other)
        self.assertEqual(1, len(self.service.list_meetings(self.other)))

    def test_workspace_storage_count_limit(self):
        with self.service.Session.begin() as session:
            session.add_all(Meeting(workspace_id=self.owner["workspace_id"], created_by=self.owner["id"], title=f"Existing {i}", source_type="transcript", transcript=TEXT) for i in range(500))
        with self.assertRaisesRegex(ValueError, "500-meeting"):
            self.create()

    def test_production_rejects_sqlite_before_starting(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}), self.assertRaisesRegex(ValueError, "PostgreSQL"):
            Service(self.url)

    def test_oidc_requires_allowlisted_verified_identity(self):
        self.service.auth_mode = "oidc"
        claims = {"email": "sso@example.test", "email_verified": True, "sub": "person-123", "iss": "https://identity.example.test", "name": "Team member"}
        with self.assertRaises(ValueError):
            self.service.oidc_login(claims)
        with patch.dict(os.environ, {"OIDC_ALLOWED_DOMAINS": "example.test"}):
            for overrides in [{"email_verified": False}, {"email_verified": "true"}, {"email": "sso@evil.test"}, {"sub": ""}, {"iss": ""}]:
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    self.service.oidc_login({**claims, **overrides})
            user = self.service.oidc_login(claims)
            self.assertEqual("sso@example.test", user["email"])
            self.assertEqual(user["id"], self.service.oidc_login(claims)["id"])


if __name__ == "__main__":
    unittest.main()
