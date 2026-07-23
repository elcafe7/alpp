"""Regression checks for credential resolution on headless hosts."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from alpp import creds
from alpp import cli


class CredentialResolutionTests(unittest.TestCase):
    def test_fail_keyring_is_not_reported_as_available(self) -> None:
        class FailBackend:
            priority = 0

        class KeyringModule:
            @staticmethod
            def get_keyring() -> FailBackend:
                return FailBackend()

        with patch.object(creds, "_keyring_module", return_value=KeyringModule()):
            self.assertFalse(creds.keyring_available())

    def test_environment_credentials_do_not_need_keyring(self) -> None:
        values = {
            "ALPACA_API_KEY": "PKTEST",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_PAPER_TRADE": "true",
        }
        with patch.dict(os.environ, values, clear=True):
            with patch.object(creds, "keyring_available", return_value=False):
                resolved = creds.resolve_credentials()

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.backend, "environment")
        self.assertTrue(resolved.paper)

    def test_missing_keyring_produces_setup_message(self) -> None:
        with patch.object(creds, "keyring_available", return_value=False):
            with self.assertRaises(SystemExit) as raised:
                creds.login_interactive(api_key="PKTEST", secret_key="secret")

        self.assertIn("No usable system keyring backend", str(raised.exception))

    def test_configured_output_directory_controls_default_html(self) -> None:
        with patch.dict(os.environ, {"ALPP_OUT": "/tmp/alpp-public"}, clear=True):
            path = cli.default_html_path("spy", "ytd")

        self.assertEqual(path.parent, cli.Path("/tmp/alpp-public"))
        self.assertTrue(path.name.startswith("SPY_ytd_"))
        self.assertEqual(path.suffix, ".html")

    def test_html_directory_target_gets_a_generated_filename(self) -> None:
        path = cli.resolve_html_path("/tmp/alpp-public", "spy", "ytd")

        self.assertEqual(path.parent, cli.Path("/tmp/alpp-public"))
        self.assertTrue(path.name.startswith("SPY_ytd_"))
