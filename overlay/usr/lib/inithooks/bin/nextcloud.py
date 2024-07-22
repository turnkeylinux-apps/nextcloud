#!/usr/bin/python3
"""Set Nextcloud admin password and domain to serve

Option:
    --pass=     unless provided, will ask interactively
    --domain=   unless provided, will ask interactively
                DEFAULT=www.example.com
"""

import sys
import getopt
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

RAND_PWD_FILE = "/root/nextcloud_random_admin_password"


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
    """
    local_env = os.environ.copy()
    local_env["OC_PASS"] = password
    p = subprocess.run(
        args=[
            "/usr/local/bin/turnkey-occ",
            "user:resetpassword",
            "--password-from-env",
            "admin",
        ],
        cwd="/var/www/nextcloud",
        env=local_env,
        text=True,
        capture_output=True,
    )
    # Success :)
    if p.returncode == SUCCESS:
        log.write("admin password set successfully")
        return (SUCCESS, "", [])

    # password setting failure/error handling
    else:
        # occ seems to only output to stdout - even if stacktrace
        # but just in case that changes
        occ_output = p.stdout + p.stderr
        services = []
        # log raw occ output - including full stacktrace if relevant
        log.write(occ_output, "err")

        # password complexity failure
        if "password" in occ_output.lower():
            error_code = ERR_PASSWORD
            msg = occ_output.rstrip()

        # nextcloud exception
        elif "exception" in occ_output.lower():
            error_code = ERR_EXCEPTION
            msg = "Nextcloud exception:"

            if "redis" in occ_output.lower():
                services.append("Redis")
            if "database" in occ_output.lower():
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
            and sum(c.isdigit() for c in random_pass)
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
                                       "pass=", "domain="])
    except getopt.GetoptError as e:
        usage(e)

    password = ""
    domain = ""
    for opt, val in opts:
        if opt in ("-h", "--help"):
            usage()
        elif opt == "--pass":
            password = val
        elif opt == "--domain":
            domain = val

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
                    print(services)
                    for service in services:
                        print(service)
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
                _ = set_random_pass()
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
                _, _ = set_random_pass()
            else:
                log.write("admin password not set due to Nextcloud error/s"
                          " - resolve problem and set manually",
                          "err")

    if not domain:
        if "d" not in locals():
            d = Dialog("TurnKey GNU/Linux - First boot configuration")

        domain = d.get_input(
            "Nextcloud Domain",
            "Enter the domain to serve Nextcloud.",
            DEFAULT_DOMAIN
        )

    if domain == "DEFAULT":
        domain = DEFAULT_DOMAIN

    sedcom = """
        /0 => 'localhost',/ a\
    1 => '%s',
    """

    inithooks_cache.write("APP_DOMAIN", domain)

    conf = "/var/www/nextcloud/config/config.php"
    subprocess.call(["sed", "-i", "/1 => /d", conf])
    subprocess.call(["sed", "-i", sedcom % domain, conf])

    sys.exit(hook_exit_code)


if __name__ == "__main__":
    main()
