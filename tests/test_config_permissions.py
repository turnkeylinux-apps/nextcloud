"""Sentinel controls for privileged configuration permission changes."""

from importlib.machinery import SourceFileLoader
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


OVERLAY = Path(__file__).resolve().parents[1] / "overlay"
HELPER = OVERLAY / "usr/local/sbin/turnkey-nextcloud-config-permissions"
loader = SourceFileLoader("nextcloud_config_permissions", str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
permissions = importlib.util.module_from_spec(spec)
loader.exec_module(permissions)


class ConfigurationPermissionsTests(unittest.TestCase):
    def test_symlink_boundaries_leave_external_sentinels_untouched(self):
        for boundary in ("config", "custom_apps", "config.php"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "nextcloud"
                root.mkdir()
                (root / "config").mkdir()
                (root / "custom_apps").mkdir()
                (root / "config/config.php").write_text("<?php // original\n")
                external = Path(directory) / "external"
                if boundary == "config.php":
                    external.write_text("sentinel\n")
                    target = root / "config/config.php"
                    target.unlink()
                else:
                    external.mkdir()
                    target = root / boundary
                    if boundary == "config":
                        (target / "config.php").unlink()
                    target.rmdir()
                external.chmod(0o700)
                before = external.stat()
                target.symlink_to(external)
                with patch.object(permissions.os, "fchown") as changed:
                    with self.assertRaises(OSError):
                        permissions.restore_permissions(str(root))
                    changed.assert_not_called()
                after = external.stat()
                self.assertEqual((after.st_uid, after.st_gid, after.st_mode),
                                 (before.st_uid, before.st_gid, before.st_mode))
                if external.is_file():
                    self.assertEqual(external.read_text(), "sentinel\n")

    def test_regular_configuration_keeps_its_contents_and_writable_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "custom_apps").mkdir()
            config = root / "config/config.php"
            config.write_text("<?php // user settings\n")
            # Ownership requires root in the installed gate; modes and writes
            # are exercised on real descriptors here without host root access.
            with patch.object(permissions.os, "fchown"):
                permissions.restore_permissions(str(root))
            self.assertEqual(stat.S_IMODE((root / "config").stat().st_mode), 0o770)
            self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o640)
            self.assertEqual(config.read_text(), "<?php // user settings\n")
            with config.open("a") as stream:
                stream.write("// supported change\n")
            self.assertIn("supported change", config.read_text())

    def test_console_wrapper_defaults_to_service_user_without_stat(self):
        wrapper = OVERLAY / "usr/local/bin/turnkey-occ"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "nextcloud"
            (root / "config").mkdir(parents=True)
            sentinel = Path(directory) / "sentinel"
            sentinel.write_text("external configuration sentinel\n")
            (root / "config/config.php").symlink_to(sentinel)
            local_wrapper = Path(directory) / "turnkey-occ"
            local_wrapper.write_text(wrapper.read_text().replace("/var/www/nextcloud", str(root)))
            local_wrapper.chmod(0o755)
            fake = Path(directory) / "runuser"
            fake.write_text('#!/bin/bash\nprintf "%s\\n" "$1"\n')
            fake.chmod(0o755)
            blocked = Path(directory) / "stat"
            # A metadata-selected privileged account must never control the
            # default command identity, even with a linked configuration.
            blocked.write_text('#!/bin/bash\nprintf "root\\n"\n')
            blocked.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = directory + os.pathsep + env["PATH"]
            env.pop("NC_USR", None)
            self.assertEqual(subprocess.check_output([str(local_wrapper), "status"], env=env, text=True).strip(), "www-data")
            env["NC_USR"] = "root"
            self.assertEqual(subprocess.check_output([str(local_wrapper), "status"], env=env, text=True).strip(), "root")
            self.assertEqual(sentinel.read_text(), "external configuration sentinel\n")


if __name__ == "__main__":
    unittest.main()
