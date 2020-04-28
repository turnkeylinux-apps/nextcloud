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
from subprocess import call
from os.path import *
from os import chdir

from dialog_wrapper import Dialog

def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)

DEFAULT_DOMAIN="www.example.com"



def main():
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
        d = Dialog('TurnKey GNU/Linux - First boot configuration')
        password = d.get_password(
            "Nextcloud Password",
            "Enter new password for the Nextcloud 'admin' account.")

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

    call(['sed', '-i', "/1 => /d", '/var/www/nextcloud/config/config.php'])
    call(['sed', '-i', sedcom % domain, '/var/www/nextcloud/config/config.php'])

    chdir("/var/www/nextcloud")
    call(['su', '-s', '/bin/sh', '-p', 'www-data', '-c', 'php /var/www/nextcloud/occ user:resetpassword --password-from-env admin'],env={"OC_PASS":password})
    call(['system', 'apache2', 'restart'])

if __name__ == "__main__":
    main()

