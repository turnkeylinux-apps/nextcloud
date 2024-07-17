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
import random
import string
import secrets

from libinithooks.dialog_wrapper import Dialog
from libinithooks.inithooks_log import InitLog
from libinithooks import inithooks_cache

DEFAULT_DOMAIN = "www.example.com"
log = InitLog("nextcloud")

ERR_PASSWORD = 1
ERR_SERVICE = 2
ERR_UNKNOWN = 3


def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)


def set_password(password: str) -> tuple[int, str]:
    """Set Nextcloud password - returns code & message
    - if succcessful - return 0
    - if password complexity failure - return ERR_PASSWORD
    - if exception - return ERR_SERVICE
    - other unknown error - return ERR_UNKNOWN
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

    # password successfully set
    if p.returncode == 0:
        log.write("admin password set")
        return (0, "")

    # failure/error handling
    else:
        skip_pass = ("\nTo skip setting password: Skip-password"
                     "\n- fix issues & set password manually")
        rand_pass = ("\nTo set random password: Random1234"
                     "\n- see inithooks log for password")
        # occ seems to only output to stdout - even if stacktrace
        # so write stdout to log regardless
        log.write(p.stdout, "err")

        # password complexity failure
        if "password" in p.stdout.lower():
            error_code = ERR_PASSWORD
            msg = f"{p.stdout}{rand_pass}"

        # nextcloud exception
        elif "exception" in p.stdout.lower():
            error_code = ERR_SERVICE
            head = "Nextcloud exception: "
            tail = ("\nAre all services running?"
                    f" See Inithooks log for info{skip_pass}")
            if "redis" in p.stdout.lower():
                tail = tail.format('redis')
                msg = f"{head}Redis problem{tail}"
            elif "database":
                msg = f"{head}Database problem{tail}"
            else:
                msg = f"{head}Unknown problem{tail}"

        # some other error
        else:
            error_code = ERR_UNKNOWN
            msg = f"Unexpected Nextcloud error{rand_pass}{skip_pass}"

        return (error_code, f"\n{msg}")


def set_random_pass():
    alphabet = string.ascii_letters + string.digits
    while True:
        random_pass = ''.join(secrets.choice(alphabet) for _ in range(32))
        if (
            any(c.islower() for c in random_pass)
            and any(c.isupper() for c in random_pass)
            and sum(c.isdigit() for c in random_pass)
        ):
            break
    while True:
        password = set_password(random_pass)
        match password[0]:
            case 0:
                # success
                pass_file = "/root/nextcloud_random_password"
                with open(pass_file) as fob:
                    fob.write(f"{random_pass}\n")
                log.write(f"admin random password set: see {pass_file}", "warn")
                return
            case 1:
                # should occur only in extremely rare cases
                # trying again should work
                continue
            case _:
                # exceptions and unknown errors
                log.write(
                    f"password setting failed - left unset:"
                    f"\n{password[1]}", "err"
                )
                return


def main():
    exit_code = 0
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

    if not password:
        message = "Enter new password for the Nextcloud 'admin' account."
        d = Dialog("TurnKey GNU/Linux - First boot configuration")
        while True:
            password = d.get_password(
                "Nextcloud Password",
                message,
                pass_req=10,
            )
            assert password is not None
            match password:
                case "Random1234":
                    password = set_random_pass()
                    exit_code = 1
                    break
                case "Skip-password":
                    log.write("admin password not set - please set manually",
                              "err")
                    exit_code = 1
                    break
                case _:
                    new_password = set_password(password)
            if new_password[0] == 0:
                break
            else:
                message = new_password[1]
    else:
        cli_password = set_password(password)
        if cli_password[0] != 0:
            log.write("setting admin password failed", "err")
            exit_code = 1
            if cli_password[0] == 1:
                set_random_pass()
            else:
                log.write("admin password not set - please set manually",
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

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
