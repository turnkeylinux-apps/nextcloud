"""Sentinel controls for privileged configuration permission changes."""

from importlib.machinery import SourceFileLoader
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
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


@unittest.skipUnless(os.geteuid() == 0, "real updater identity/ownership test requires root")
class UpdaterPermissionsTests(unittest.TestCase):
    def exercise_updater(self, fail=False):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            parent.chmod(0o755)  # Allow the real service identity to traverse.
            root = parent / "nextcloud"
            root.mkdir()
            for name in ("config", "custom_apps", "updater"):
                (root / name).mkdir()
            data = parent / "data"
            data.mkdir()
            original = {
                ".htaccess": ("deny public config\n", 0, 0, 0o644),
                "config.sample.php": ("sample\n", 0, 0, 0o644),
                "config.php": ("<?php // configured account\n", 33, 33, 0o640),
                "owner.config.php": ("<?php\n$CONFIG = array('config_is_read_only' => true, 'owner_option' => 'keep');\n", 0, 33, 0o440),
            }
            for name, (content, uid, gid, mode) in original.items():
                path = root / "config" / name
                path.write_text(content)
                os.chown(path, uid, gid)
                path.chmod(mode)
            (root / "index.php").write_text("core\n")
            (root / "updater/updater.phar").write_text(r"""
import os
from pathlib import Path
root = Path(__file__).resolve().parents[1]
assert os.geteuid() == 33
assert (root / 'config').stat().st_uid == 0
# Mirror official Updater::checkWritePermissions: real service-user access to
# every recursive entry, including existing config scaffold/custom files.
blocked = [str(p) for p in root.rglob('*') if not os.access(p, os.W_OK)]
assert not blocked, 'upstream writable criterion rejected: ' + repr(blocked)
for name in ('.htaccess', 'config.sample.php', 'config.php'):
    replacement = root / 'config' / (name + '.new')
    replacement.write_text('upgraded ' + name + '\n')
    replacement.replace(root / 'config' / name)
p = root / 'config/generated.config.php'
p.write_text('generated configuration\n')
p.chmod(0o640)
if os.environ.get('QA_UPDATE_FAIL'):
    raise SystemExit(42)
""")
            (root / "occ").write_text("import os\nassert os.geteuid() == 33\n")
            # Keep production permission preparation, runuser, helper finally
            # and outer EXIT trap. Only replace PHP with a contract probe.
            helper = parent / "config-permissions"
            helper.write_text(HELPER.read_text().replace("/var/www/nextcloud", str(root)))
            helper.chmod(0o755)
            updater = parent / "update"
            source = (OVERLAY / "usr/local/sbin/turnkey-nextcloud-update").read_text()
            source = source.replace("/var/www/nextcloud-data", str(data))
            source = source.replace("/var/www/nextcloud", str(root))
            source = source.replace("/usr/local/sbin/turnkey-nextcloud-config-permissions", str(helper))
            source = source.replace("/var/www/.turnkey-nextcloud-read-only.config.php.disabled", str(parent / "parked.php"))
            updater.write_text(source.replace("/usr/bin/php", sys.executable))
            env = os.environ.copy()
            if fail:
                env["QA_UPDATE_FAIL"] = "1"
            result = subprocess.run(["bash", str(updater)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 42 if fail else 0, result.stderr)
            self.assertIn("upgraded", (root / "config/config.sample.php").read_text())
            for name, (_, uid, gid, mode) in original.items():
                path = root / "config" / name
                st = path.stat()
                self.assertEqual((st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)),
                                 (uid, gid, mode), name)
            self.assertEqual((root / "config/owner.config.php").read_text(), original['owner.config.php'][0])
            self.assertEqual((root / "config").stat().st_uid, 0)
            self.assertEqual(stat.S_IMODE((root / "config").stat().st_mode), 0o770)
            self.assertEqual((root / "index.php").stat().st_uid, 0)
            self.assertEqual(stat.S_IMODE((root / "index.php").stat().st_mode), 0o644)
            generated = (root / "config/generated.config.php").stat()
            self.assertEqual((generated.st_uid, stat.S_IMODE(generated.st_mode)), (33, 0o640))

    def test_actual_prepare_passes_upstream_criterion_and_restores_replacements(self):
        self.exercise_updater()

    def test_command_failure_restores_config_and_outer_core_permissions(self):
        self.exercise_updater(fail=True)


class UpdaterBoundaryTests(unittest.TestCase):
    def test_unsupported_config_entries_fail_before_any_grant(self):
        for kind in ("symlink", "directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / "config"
                config.mkdir()
                (config / "config.php").write_text("main\n")
                outside = root / "sentinel"
                outside.write_text("outside policy\n")
                before = outside.stat()
                if kind == "symlink":
                    (config / "owner.config.php").symlink_to(outside)
                else:
                    (config / "unsupported").mkdir()
                with patch.object(permissions.os, "fchown") as changed:
                    with self.assertRaises((OSError, RuntimeError)):
                        permissions.run_with_writable_config(["false"], str(root))
                    changed.assert_not_called()
                self.assertEqual(outside.read_text(), "outside policy\n")
                self.assertEqual(outside.stat().st_mode, before.st_mode)


if __name__ == "__main__":
    unittest.main()
