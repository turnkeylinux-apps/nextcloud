Nextcloud - Share files, music, calendar
========================================

`Nextcloud`_ helps store your files, folders, contacts, photo galleries,
calendars and more on a server of your choosing. Access that folder from
your mobile device, your desktop, or a web browser. Access your data
wherever you are, when you need it.

This appliance includes all the standard features in `TurnKey Core`_,
and on top of that:

- Nextcloud Server:
   
   - Installed from official zip file to /var/www/nextcloud. No automatic
     updates.
   - Data directory (/var/www/nextcloud-data) outside the webroot (security).
   - Includes occ_ script for command line administration and configuration.
     Also includes turnkey-occ_ wrapper script (runs occ as www-data user).

     **Security note**: Updates to Nextcloud may require supervision so
     they **ARE NOT** configured to install automatically. See `Nextcloud
     documentation`_ for upgrading.

- SSL support out of the box.
- `Adminer`_ administration frontend for MySQL (listening on port
  12322 - uses SSL).
- Postfix MTA (bound to localhost) to allow sending of email (e.g.,
  password recovery).
- Webmin modules for configuring Apache2, PHP, MySQL and Postfix.

Nextcloud Updating | PHP Upgrade
-------------------------------------------
Altought it might be simple for you NextCloud is a very Enterprise Heavy Duty Application
and many people may ask: How do I update nextcloud?

It is preatty Straight forward in the Configuration>General>Update Tab but you might encounter PHP update issues.

[@JedMeister Already talked about it here](https://www.turnkeylinux.org/forum/support/wed-20220824-1719/update-php-tkl-wordpress#comment-51808)

[And also here](https://www.turnkeylinux.org/forum/support/fri-20211203-1615/upgrading-php-7329-php-7333#comment-50598)

From Version 23 and over PHP7.4 is recomended but is not a smooth update, be sure to have a backup of your instance.
Some packages aren't in the system in 7.3 and as JedScript is based on used NextCloud PHP previusly installed packages it might crash.

'''
apt install php7.4-redis
'''
is missing from the procedure.


Credentials *(passwords set at first boot)*
-------------------------------------------

-  Webmin, SSH, MySQL: username **root**
-  Adminer: username **adminer**
-  Nextcloud: username **admin**


.. _Nextcloud: https://nextcloud.com/
.. _TurnKey Core: https://www.turnkeylinux.org/core
.. _occ: https://docs.nextcloud.com/server/stable/admin_manual/configuration_server/occ_command.html
.. _turnkey-occ: https://github.com/turnkeylinux-apps/nextcloud/blob/master/overlay/usr/local/bin/turnkey-occ
.. _Nextcloud documentation: https://docs.nextcloud.com/server/stable/admin_manual/maintenance/upgrade.html
.. _Adminer: https://www.adminer.org
