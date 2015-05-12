#!/usr/bin/python
"""Set ownCloud admin password

Option:
    --pass=     unless provided, will ask interactively

"""

import sys
import getopt
import subprocess
from subprocess import PIPE
from os.path import *

from dialog_wrapper import Dialog
from mysqlconf import MySQL

def usage(s=None):
    if s:
        print >> sys.stderr, "Error:", s
    print >> sys.stderr, "Syntax: %s [options]" % sys.argv[0]
    print >> sys.stderr, __doc__
    sys.exit(1)

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
                                       ['help', 'pass='])
    except getopt.GetoptError, e:
        usage(e)

    password = ""
    email = ""
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()
        elif opt == '--pass':
            password = val

    if not password:
        d = Dialog('TurnKey Linux - First boot configuration')
        password = d.get_password(
            "ownCloud Password",
            "Enter new password for the ownCloud 'admin' account.")

    # make sure MySQL is running when we call the OCServer hasher in owncloud_pass.php
    m = MySQL()

    command = ["php", join(dirname(__file__), 'owncloud_pass.php'), password]
    p = subprocess.Popen(command, stdin=PIPE, stdout=PIPE, shell=False)
    stdout, stderr = p.communicate()
    if stderr:
        fatal(stderr)

    cryptpass = stdout.strip()

    m.execute('UPDATE owncloud.users SET password=\"%s\" WHERE uid=\"admin\";' % cryptpass)
    m.execute('UPDATE owncloud.preferences SET configvalue = 1 where userid = \"admin\" and appid = \"firstrunwizard\" and configkey = \"show\"')
    m.execute('DELETE FROM owncloud.preferences where userid = \"admin\" and appid = \"login\" and configkey = \"lastLogin\"')


if __name__ == "__main__":
    main()

