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
import time
import os
import random
import string

from libinithooks.dialog_wrapper import Dialog

DEFAULT_DOMAIN = "www.example.com"


def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)


def set_password(password, interactive):
    local_env = os.environ.copy()
    local_env["OC_PASS"] = password
    success = True
    try:
        subprocess.run(
                    args=['/usr/local/bin/turnkey-occ', 'user:resetpassword',
                          '--password-from-env', 'admin'],
                    cwd='/var/www/nextcloud',
                    env=local_env,
                    text=True,
                    capture_output=True,
                    check=True)
    except subprocess.CalledProcessError as e:
        success = False
        print(e.stdout)
        print(e.stderr, file=sys.stderr)
        # if interactive, ideally we should wait for user to read and then
        # click an 'ok' button, but 10 sec sleep will do for now
        if interactive:
            time.sleep(10)
    return success


def main():
    exit_code = 0
    opts = []
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
                                       ['help', 'pass=', 'domain='])
    except getopt.GetoptError as e:
        usage(e)

    password = ""
    domain = ""
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()
        elif opt == '--pass':
            password = val
        elif opt == '--domain':
            domain = val
    if not password:
        prefix = ""
        d = Dialog('TurnKey GNU/Linux - First boot configuration')
        while True:
            password = d.get_password(
                "Nextcloud Password",
                prefix + "Enter new password for the Nextcloud 'admin'"
                " account.",
                pass_req=10)
            if set_password(password, True):
                break
            else:
                prefix = "Please try again\n"
    else:
        if not set_password(password, False):
            exit_code = 1
            chars = string.ascii_letters + string.digits + string.punctuation
            new_pass = ''.join(random.choices(chars, k=36))
            print(f"Setting password '{password}' failed", file=sys.stderr)
            print(f"Setting random password: {new_pass}", file=sys.stderr)
            set_password(new_pass, False)

    if not domain:
        if 'd' not in locals():
            d = Dialog('TurnKey GNU/Linux - First boot configuration')

        domain = d.get_input(
            "Nextcloud Domain",
            "Enter the domain to serve Nextcloud.",
            DEFAULT_DOMAIN)

    if domain == "DEFAULT":
        domain = DEFAULT_DOMAIN

    sedcom = """
        /0 => 'localhost',/ a\
    1 => '%s',
    """

    conf = '/var/www/nextcloud/config/config.php'
    subprocess.call(['sed', '-i', "/1 => /d", conf])
    subprocess.call(['sed', '-i', sedcom % domain, conf])

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
