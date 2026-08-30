#!/usr/bin/python3
"""Set Nextcloud admin password and domain to serve

Option:
    --pass=     unless provided, will ask interactively
    --pass-stdin
                read the password from standard input
    --domain=   unless provided, will ask interactively
                DEFAULT=www.example.com
"""

import sys
import getopt
import grp
import subprocess
import os
import string
import secrets

from libinithooks.dialog_wrapper import Dialog
from libinithooks.inithooks_log import InitLog
from libinithooks import inithooks_cache

DEFAULT_DOMAIN = "www.example.com"
log = InitLog("nextcloud")

# set_password return value constants
SUCCESS = 0
ERR_PASSWORD = 1
ERR_EXCEPTION = 2
ERR_UNKNOWN = 3
ERR_VERIFY = 4

RAND_PWD_FILE = "/root/nextcloud_random_admin_password"
READ_ONLY_CONF = "/var/www/nextcloud/config/turnkey-read-only.config.php"
READ_ONLY_CONFIG = """<?php
$CONFIG = array(
    'config_is_read_only' => true,
);
"""


def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)


def set_password(password: str) -> tuple[int, str, list[str]]:
    """Set Nextcloud password
    returns exit_code, message & list of failed services
        exit_code is one of:
            - SUCCESS
            - ERR_PASSWORD
            - ERR_EXCEPTION
            - ERR_UNKNOWN
            - ERR_VERIFY
    """
    # Feed the requested password directly to Nextcloud's user backend on
    # stdin. The occ console cannot run as www-data after config.php becomes
    # root-owned, while the backend API preserves Nextcloud password policy
    # and password-updated events without weakening the ownership boundary.
    setter = (
        'define("OC_CONSOLE", 1); '
        'require_once "/var/www/nextcloud/lib/base.php"; '
        '$password = rtrim(stream_get_contents(STDIN), "\\r\\n"); '
        '$user = \\OCP\\Server::get(\\OCP\\IUserManager::class)'
        '->get("admin"); '
        'exit($user !== null && $user->setPassword($password) ? 0 : 1);'
    )
    p = subprocess.run(
        args=[
            "runuser",
            "-u",
            "www-data",
            "--",
            "/usr/bin/php",
            "-r",
            setter,
        ],
        input=f"{password}\n",
        cwd="/var/www/nextcloud",
        text=True,
        capture_output=True,
    )
    # Success :)
    if p.returncode == SUCCESS:
        # Do not trust the command exit status alone: verify the persisted
        # password through Nextcloud's user backend before reporting success.
        # The password is supplied on stdin, never in argv or the environment.
        verify = subprocess.run(
            args=[
                "runuser",
                "www-data",
                "-s",
                "/bin/bash",
                "-c",
                "/usr/bin/php -r 'define(\"OC_CONSOLE\", 1); "
                "require_once \"/var/www/nextcloud/lib/base.php\"; "
                "$password = rtrim(stream_get_contents(STDIN), \"\\r\\n\"); "
                "exit(\\OCP\\Server::get(\\OCP\\IUserManager::class)"
                "->checkPassword(\"admin\", $password) === false ? 1 : 0);'",
            ],
            input=f"{password}\n",
            cwd="/var/www/nextcloud",
            text=True,
            capture_output=True,
        )
        if verify.returncode == SUCCESS:
            log.write("admin password set and verified successfully")
            return (SUCCESS, "", [])
        log.write("admin password verification failed after reset", "err")
        return (
            ERR_VERIFY,
            "Nextcloud did not accept the new admin password after resetting it.",
            [],
        )

    # password setting failure/error handling
    else:
        # Preserve backend output for existing error classification and the
        # inithook log without exposing the stdin-only password.
        backend_output = p.stdout + p.stderr
        services = []
        log.write(backend_output, "err")

        # password complexity failure
        if "password" in backend_output.lower():
            error_code = ERR_PASSWORD
            msg = backend_output.rstrip()

        # nextcloud exception
        elif "exception" in backend_output.lower():
            error_code = ERR_EXCEPTION
            msg = "Nextcloud exception:"

            if "redis" in backend_output.lower():
                services.append("Redis")
            if "database" in backend_output.lower():
                services.append("MariaDB")
            if services:
                msg = f"{msg} Can't connect to service(s)"
            else:
                msg = f"{msg} Unknown exception"

        # any other unknown/unexpected error
        else:
            error_code = ERR_UNKNOWN
            msg = f"Unexpected Nextcloud error"

        return (error_code, msg, services)


def set_random_pass() -> tuple[int, str]:
    """Returns exit_code & msg"""
    chars = string.ascii_letters + string.digits
    while True:
        random_pass = ''.join(secrets.choice(chars) for _ in range(32))
        if (
            any(c.islower() for c in random_pass)
            and any(c.isupper() for c in random_pass)
            and any(c.isdigit() for c in random_pass)
        ):
            break
    while True:
        exit_code, msg, _ = set_password(random_pass)
        if exit_code == ERR_PASSWORD:
            # a 32 char random string should never have this condition, but
            # if it does, then retrying should resolve it
            continue
        else:
            if exit_code == SUCCESS:
                with open(RAND_PWD_FILE, "w") as fob:
                    fob.write(f"{random_pass}\n")
                msg = f"Admin user random password set: see {RAND_PWD_FILE}"
                log.write(msg, "warn")
            else:
                # all other errors
                msg = f"Setting password failed - left unset:\n{msg}"
                log.write(msg, "err")
            return (exit_code, msg)


def err_response_choice(
        dialog: Dialog,
        title: str,
        msg: str,
        option1: str,
        option2: str
) -> str:
    choice = dialog.yesno(
            title=title,
            text=msg,
            yes_label=option1.capitalize(),
            no_label=option2.capitalize()
    )
    if choice:
        return option1
    else:
        return option2


def main():
    hook_exit_code = 0
    opts = []
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", ["help",
                                       "pass=", "pass-stdin", "domain="])
    except getopt.GetoptError as e:
        usage(e)

    password = ""
    domain = ""
    for opt, val in opts:
        if opt in ("-h", "--help"):
            usage()
        elif opt == "--pass":
            password = val
        elif opt == "--pass-stdin":
            password = sys.stdin.readline().rstrip("\r\n")
        elif opt == "--domain":
            domain = val

    # Complete all config.php mutations before setting the administrator
    # password. This keeps the final password verification authoritative for
    # the exact configuration that Apache will load.
    if not domain:
        d = Dialog("TurnKey GNU/Linux - First boot configuration")
        domain = d.get_input(
            "Nextcloud Domain",
            "Enter the domain to serve Nextcloud.",
            DEFAULT_DOMAIN
        )

    if domain == "DEFAULT":
        domain = DEFAULT_DOMAIN

    inithooks_cache.write("APP_DOMAIN", domain)
    occ_env = os.environ.copy()
    occ_env["NC_USR"] = "root"
    subprocess.run([
        "/usr/local/bin/turnkey-occ", "config:system:set",
        "trusted_domains", "1", f"--value={domain}"
    ], env=occ_env, check=True)
    conf = "/var/www/nextcloud/config/config.php"
    os.chown(conf, 0, grp.getgrnam("www-data").gr_gid)
    os.chmod(conf, 0o640)

    # Establish the final merged configuration before setting the password.
    # Nextcloud must generate and verify the credential under the same
    # read-only configuration that Apache and later CLI processes load.
    subprocess.run(
        [
            "/usr/bin/install",
            "-o",
            "root",
            "-g",
            "www-data",
            "-m",
            "0640",
            "/dev/stdin",
            READ_ONLY_CONF,
        ],
        input=READ_ONLY_CONFIG,
        text=True,
        check=True,
    )

    random = (
        "Random",
        f" - Set random admin password; will be saved to {RAND_PWD_FILE}"
    )
    skip = (
        "Skip",
        " - Skip setting an admin password & set manually later"
    )
    retry = (
        "Retry",
        " - Try setting the admin password again"
    )
    if not password:
        d = Dialog("TurnKey GNU/Linux - First boot configuration")

        while True:
            password = d.get_password(
                "Nextcloud Password",
                "Enter new password for the Nextcloud 'admin' account.",
                pass_req=10,
            )
            assert password is not None
            exit_code, msg, services = set_password(password)

            if exit_code == SUCCESS:
                break
            title = "Nextcloud Error"
            if exit_code == ERR_PASSWORD:
                msg = (f"{msg}\n\nRetry or set a random password."
                       f"\n\n{''.join(retry)} (recommended)"
                       f"\n\n{''.join(random)}")
                option1 = retry[0]
                option2 = random[0]

            # handle non-password related errors
            else:
                hook_exit_code = 1
                if exit_code == ERR_EXCEPTION:
                    for service in services:
                        msg = f"{msg}\n - failed to connect to: {service}"
                else:
                    msg = ("An unrecognised error has occured:"
                           f"\n{msg}")
                msg = (f"{msg}\n\nThis error is likely unrecoverable until"
                       " the underlying issue is resolved. Check log for"
                       " for more detals.\n\nIt is recommended that you skip"
                       " password and investigate the issue."
                       f"\n\n{''.join(skip)} (recommended)"
                       f"\n\n{''.join(retry)}")
                option1 = skip[0]
                option2 = retry[0]
            choice = err_response_choice(
                    d,
                    title,
                    msg,
                    option1,
                    option2
            )
            if choice == "Skip":
                log.write("Skipping password setting due to issues. Be sure to"
                          " manually set a password once resolved")
                break
            elif choice == "Random":
                exit_code, msg = set_random_pass()
                if exit_code != 0:
                    hook_exit_code = 1
                    d.error(f"{msg}\n\n Ok to continue and check logs"
                            " to debug issue")
                break
            else:  # choice == "Retry"
                log.write("Retrying setting password", "info")
                continue

    else:
        exit_code, _, _ = set_password(password)
        if exit_code != 0:
            log.write("setting admin password failed", "err")
            hook_exit_code = 1
            if exit_code == ERR_PASSWORD:
                exit_code, _ = set_random_pass()
            if exit_code != 0:
                log.write("admin password not set due to Nextcloud error/s"
                          " - resolve problem and set manually",
                          "err")

    sys.exit(hook_exit_code)


if __name__ == "__main__":
    main()
