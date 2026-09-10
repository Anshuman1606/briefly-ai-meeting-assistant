"""User workflows through Streamlit widgets and a real isolated service/database."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from briefly.service import Service


APP_FILE = Path(__file__).resolve().parent.parent / "app.py"
TRANSCRIPT = """[00:00] Maya: We decided to launch the customer dashboard on October 15.
[00:30] Arjun: I will test the CSV export by October 9.
[01:00] Priya: I will complete the security review by October 10.
[01:30] Maya: Which customer team will join the pilot first?"""


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="briefly-ui-test-")
        self.env_values = {
            "APP_ENV": "local", "AUTH_MODE": "password", "ALLOW_SIGNUP": "true",
            "TRANSCRIPTION_BACKEND": "disabled", "BRIEFLY_EMBEDDED_WORKER": "false",
            "MISTRAL_API_KEY": "", "SARVAM_API_KEY": "", "OIDC_ALLOWED_DOMAINS": "",
            "DATABASE_URL": "sqlite:///" + str(Path(self.temp.name) / "ui.db"),
        }
        self.env = patch.dict(os.environ, self.env_values)
        self.env.start()
        # An operator's global Streamlit settings must not affect this fixture.
        self.config_files = patch("streamlit.config.get_config_files", side_effect=lambda filename: [str(APP_FILE.parent / ".streamlit" / filename)])
        self.config_files.start()
        st.cache_resource.clear()
        self.service = Service()
        # App reruns share this actual service; only its construction is intercepted.
        self.factory = patch("briefly.service.Service", return_value=self.service)
        self.factory.start()
        self.app = AppTest.from_file(APP_FILE, default_timeout=15)
        self.app.secrets.update(self.env_values)
        self.app.run()
        self.assert_healthy()

    def tearDown(self):
        st.cache_resource.clear()
        self.factory.stop()
        self.service.stop_worker()
        self.service.engine.dispose()
        self.config_files.stop()
        self.env.stop()
        self.temp.cleanup()

    def element(self, kind, label):
        matches = [element for element in getattr(self.app, kind) if element.label == label]
        self.assertEqual(1, len(matches), f"Expected one {kind} labelled {label!r}")
        return matches[0]

    def click(self, label):
        self.element("button", label).click().run()
        self.assert_healthy()

    def assert_healthy(self):
        self.assertEqual([], [element.message for element in self.app.exception])
        # app.main catches unexpected errors, so checking exceptions alone is insufficient.
        self.assertEqual([], [element.value for element in self.app.error])

    def signup(self):
        for label, value in {
            "Username": "alice", "Email": "alice@example.test",
            "Workspace name": "Atlas product team", "Choose a password": "VeryStrongPassword!42",
            "Confirm password": "VeryStrongPassword!42",
        }.items():
            self.element("text_input", label).set_value(value)
        self.click("Create your workspace")
        self.assertEqual("library", self.app.session_state["page"])
        self.assertEqual("alice@example.test", self.app.session_state["user"]["email"])
        self.assertEqual([], self.service.list_meetings(self.app.session_state["user"]))

    def test_landing_signup_logout_and_login(self):
        self.assertIn("Good conversations.\nClear next steps.", [element.value for element in self.app.title])
        self.signup()
        original = dict(self.app.session_state["user"])
        self.click("Sign out")
        with self.assertRaises(ValueError):
            self.service.list_meetings(original)

        self.element("text_input", "Username or email").set_value("alice@example.test")
        self.element("text_input", "Password").set_value("wrong-password")
        self.element("button", "Sign in →").click().run()
        self.assertEqual([], [element.message for element in self.app.exception])
        self.assertIn("Invalid username or password.", [element.value for element in self.app.error])

        self.element("text_input", "Password").set_value("VeryStrongPassword!42")
        self.click("Sign in →")
        current = self.app.session_state["user"]
        self.assertEqual(original["id"], current["id"])
        self.assertNotEqual(original["token"], current["token"])

    def test_import_process_chat_complete_action_and_prepare_reports(self):
        self.signup()
        self.click("New meeting")
        self.element("text_input", "Meeting title").set_value("Atlas launch review")
        self.element("text_area", "Meeting transcript").set_value(TRANSCRIPT)
        self.element("selectbox", "Language").set_value("English")
        self.click("Create meeting →")
        user = self.app.session_state["user"]
        meeting_id = self.app.session_state["meeting_id"]
        self.assertEqual("detail", self.app.session_state["page"])
        self.assertEqual("queued", self.service.get_meeting(user, meeting_id)["status"])
        self.assertIn("Waiting for a worker…", [element.value for element in self.app.info])

        self.assertTrue(self.service.process_next())
        self.app.run()
        self.assert_healthy()
        report = self.service.get_meeting(user, meeting_id)
        self.assertEqual("ready", report["status"])
        self.assertEqual("extractive", report["analysis_mode"])
        self.assertGreaterEqual(len(report["actions"]), 2)

        self.element("text_input", "Your question").set_value("Who will test the CSV export?")
        self.click("Ask meeting →")
        chats = self.service.get_meeting(user, meeting_id)["chats"]
        self.assertEqual(1, len(chats))
        self.assertTrue(chats[0]["citations"])
        self.assertEqual(2, len(self.app.chat_message))

        action_id = report["actions"][0]["id"]
        self.app.button(key="detail_action_" + action_id).click().run()
        self.assert_healthy()
        action = next(action for action in self.service.get_meeting(user, meeting_id)["actions"] if action["id"] == action_id)
        self.assertEqual("done", action["status"])

        for fmt in ("PDF", "TXT", "JSON"):
            self.element("radio", "Report format").set_value(fmt).run()
            self.assert_healthy()
            self.click("Prepare report")
            prepared = self.app.session_state["prepared_export"]
            self.assertEqual(meeting_id, prepared["meeting_id"])
            self.assertEqual(fmt.lower(), prepared["format"])
            self.assertIsInstance(prepared["data"], bytes)
            if fmt == "PDF":
                self.assertTrue(prepared["data"].startswith(b"%PDF-"))
            elif fmt == "TXT":
                self.assertIn("Atlas launch review", prepared["data"].decode())
            else:
                self.assertEqual(TRANSCRIPT, json.loads(prepared["data"])["transcript"])
            self.assertEqual(1, len(self.app.get("download_button")))

        self.click("Action items")
        self.element("radio", "Show actions").set_value("Completed").run()
        self.assert_healthy()
        self.assertEqual("Reopen", self.app.button(key="workspace_action_" + action_id).label)
        for navigation, expected_title in (("Team", "Your team"), ("Activity log", "Activity log"), ("Settings", "Settings"), ("Meeting library", "Meeting library")):
            self.click(navigation)
            self.assertIn(expected_title, [element.value for element in self.app.title])

    def test_private_demo_processes_real_sample(self):
        self.click("Explore the demo")
        user = self.app.session_state["user"]
        self.assertTrue(user["demo"])
        meetings = self.service.list_meetings(user)
        self.assertEqual(1, len(meetings))
        self.assertEqual("queued", meetings[0]["status"])
        self.assertTrue(self.service.process_next())
        self.app.run()
        self.assert_healthy()
        self.click("Open →")
        report = self.service.get_meeting(user, meetings[0]["id"])
        self.assertEqual("ready", report["status"])
        self.assertTrue(report["summary"])
        self.click("What was decided?")
        self.assertEqual(1, len(self.service.get_meeting(user, meetings[0]["id"])["chats"]))


if __name__ == "__main__":
    unittest.main()
