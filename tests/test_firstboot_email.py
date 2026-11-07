"""Firstboot recovery-address behavior without a running Nextcloud instance."""

import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


HOOK = Path(__file__).resolve().parents[1] / "overlay/usr/lib/inithooks/bin/nextcloud.py"


class RecoveryEmailTests(unittest.TestCase):
    def setUp(self):
        package = ModuleType("libinithooks")
        dialog = ModuleType("libinithooks.dialog_wrapper")
        dialog.Dialog = MagicMock()
        dialog.EMAIL_RE = re.compile(r"(?:^|\s).*\S@\S+(?:\s|$)", re.IGNORECASE)
        logging = ModuleType("libinithooks.inithooks_log")
        logging.InitLog = MagicMock()
        cache = ModuleType("libinithooks.inithooks_cache")
        cache.write = MagicMock()
        package.inithooks_cache = cache
        modules = {
            "libinithooks": package,
            "libinithooks.dialog_wrapper": dialog,
            "libinithooks.inithooks_log": logging,
            "libinithooks.inithooks_cache": cache,
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("nextcloud_firstboot", HOOK)
            self.hook = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.hook)
        self.cache = cache
        self.dialog = dialog.Dialog.return_value
        self.dialog.get_email.return_value = "Owner@Example.org"
        self.dialog.get_input.return_value = "cloud.example.org"
        self.dialog.get_password.return_value = "new-password"
        self.email = ""
        self.events = []
        self.calls = []

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        if "user:info" in args:
            return SimpleNamespace(stdout=json.dumps({"email": self.email}))
        if "user:setting" in args:
            self.events.append("email")
            self.email = args[-1].removeprefix("--value=")
        return SimpleNamespace(stdout="", returncode=0)

    def password(self, value):
        self.events.append("password")
        return (self.hook.SUCCESS, "", [])

    def run_main(self, args, stdin=""):
        with (
            patch.object(sys, "argv", [str(HOOK), *args]),
            patch.object(sys, "stdin", io.StringIO(stdin)),
            patch.object(sys, "stderr", io.StringIO()) as errors,
            patch.object(self.hook.subprocess, "run", side_effect=self.run_command),
            patch.object(self.hook.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=33)),
            patch.object(self.hook.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=33)),
            patch.object(self.hook.os.path, "exists", return_value=False),
            patch.object(self.hook.os, "chown"),
            patch.object(self.hook.os, "chmod"),
            patch.object(self.hook, "set_password", side_effect=self.password),
        ):
            with self.assertRaises(SystemExit) as raised:
                self.hook.main()
        return raised.exception.code, errors.getvalue()

    def test_normal_setup_prompts_and_applies_after_password(self):
        code, _ = self.run_main([])
        self.assertEqual(code, 0)
        self.dialog.get_email.assert_called_once()
        self.assertEqual(self.events, ["password", "email"])
        self.assertEqual(self.email, "owner@example.org")
        self.cache.write.assert_any_call("APP_EMAIL", "owner@example.org")

    def test_new_preseed_applies_normalized_email_and_default_domain(self):
        code, _ = self.run_main(
            ["--pass-stdin", "--domain=DEFAULT", "--email= Owner@Example.org "],
            stdin="new-password\n",
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.events, ["password", "email"])
        self.cache.write.assert_any_call("APP_DOMAIN", self.hook.DEFAULT_DOMAIN)
        self.cache.write.assert_any_call("APP_EMAIL", "owner@example.org")
        self.hook.Dialog.assert_not_called()

    def test_legacy_complete_preseed_fails_before_mutations_or_prompts(self):
        for domain in ("DEFAULT", "cloud.example.org"):
            with self.subTest(domain=domain):
                code, error = self.run_main(["--pass-stdin", f"--domain={domain}"], "new-password\n")
                self.assertEqual(code, 1)
                self.assertIn("APP_EMAIL/--email is required", error)
        self.assertFalse(self.events)
        self.cache.write.assert_not_called()
        self.assertTrue(all("user:info" in args for args in self.calls))
        self.hook.Dialog.assert_not_called()

    def test_omitted_email_preserves_actual_user_setting(self):
        self.email = "existing@example.org"
        code, _ = self.run_main(["--pass=new-password", "--domain=DEFAULT"])
        self.assertEqual(code, 0)
        self.assertEqual(self.email, "existing@example.org")
        self.assertEqual(self.events, ["password"])
        self.assertNotIn("APP_EMAIL", [call.args[0] for call in self.cache.write.call_args_list])
        self.hook.Dialog.assert_not_called()

    def test_explicit_change_replaces_existing_address(self):
        self.email = "existing@example.org"
        code, _ = self.run_main(["--pass=new-password", "--domain=DEFAULT", "--email=new@example.org"])
        self.assertEqual(code, 0)
        self.assertEqual(self.email, "new@example.org")
        self.assertEqual(self.events, ["password", "email"])

    def test_invalid_preseed_fails_before_mutations(self):
        code, error = self.run_main(["--pass=new-password", "--domain=DEFAULT", "--email=DEFAULT"])
        self.assertEqual(code, 1)
        self.assertIn("email is not valid", error)
        self.assertFalse(self.calls)
        self.cache.write.assert_not_called()

    def test_failed_password_does_not_change_email(self):
        self.password = MagicMock(return_value=(self.hook.ERR_UNKNOWN, "failure", []))
        code, _ = self.run_main(["--pass=new-password", "--domain=DEFAULT", "--email=owner@example.org"])
        self.assertEqual(code, 1)
        self.assertFalse(any("user:setting" in args for args in self.calls))
        self.assertNotIn("APP_EMAIL", [call.args[0] for call in self.cache.write.call_args_list])

    def test_mismatched_readback_is_not_cached(self):
        with patch.object(self.hook.subprocess, "run", return_value=SimpleNamespace(stdout='{"email":"other@example.org"}')):
            with self.assertRaisesRegex(RuntimeError, "verification failed"):
                self.hook.set_admin_email("owner@example.org")
        self.cache.write.assert_not_called()

    def test_failed_backend_write_is_not_cached(self):
        with patch.object(self.hook.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "occ")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.hook.set_admin_email("owner@example.org")
        self.cache.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
