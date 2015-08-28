#!/usr/bin/python
"""Set ownCloud admin password and domain to serve

Option:
    --pass=     unless provided, will ask interactively
    --domain=   unless provided, will ask interactively
                DEFAULT=www.example.com
"""

import sys
import getopt
import subprocess
from subprocess import Popen, PIPE, call
from os.path import *

from dialog_wrapper import Dialog
from mysqlconf import MySQL

def usage(s=None):
    if s:
        print >> sys.stderr, "Error:", s
    print >> sys.stderr, "Syntax: %s [options]" % sys.argv[0]
    print >> sys.stderr, __doc__
    sys.exit(1)

DEFAULT_DOMAIN="www.example.com"

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
                                       ['help', 'pass=', 'domain='])
    except getopt.GetoptError, e:
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
        d = Dialog('TurnKey Linux - First boot configuration')
        password = d.get_password(
            "ownCloud Password",
            "Enter new password for the ownCloud 'admin' account.")

    if not domain:
        if 'd' not in locals():
            d = Dialog('TurnKey Linux - First boot configuration')

        domain = d.get_input(
            "OwnCloud Domain",
            "Enter the domain to serve OwnCloud.",
            DEFAULT_DOMAIN)

    if domain == "DEFAULT":
        domain = DEFAULT_DOMAIN

    # make sure MySQL is running when we call the OCServer hasher in owncloud_pass.php
    m = MySQL()

    command = ["php", join(dirname(__file__), 'owncloud_pass.php'), password]
    p = Popen(command, stdin=PIPE, stdout=PIPE)
    stdout, stderr = p.communicate()
    if stderr:
        fatal(stderr)

    cryptpass = stdout.strip()

    sedcom = """
        /0 => '127.0.0.1',/ a\
    '1' => '%s',
    """

    call(['sed', '-i', sedcom % domain, '/usr/share/owncloud/config/config.php'])

    m.execute('UPDATE owncloud.users SET password=\"%s\" WHERE uid=\"admin\";' % cryptpass)
    m.execute('UPDATE owncloud.preferences SET configvalue = 1 where userid = \"admin\" and appid = \"firstrunwizard\" and configkey = \"show\"')
    m.execute('DELETE FROM owncloud.preferences where userid = \"admin\" and appid = \"login\" and configkey = \"lastLogin\"')


if __name__ == "__main__":
    main()

