Nextcloud - Share files, music, calendar
========================================

`Nextcloud`_ helps store your files, folders, contacts, photo galleries,
calendars and more on a server of your choosing. Access that folder from
your mobile device, your desktop, or a web browser. Access your data
wherever you are, when you need it.

This appliance includes all the standard features in `TurnKey Core`_,
and on top of that:

- Nextcloud Server:
   
   - Installed from a pinned official zip file to /var/www/nextcloud. No
     automatic core updates.
   - Data directory (/var/www/nextcloud-data) outside the webroot (security).
   - Includes occ_ script for command line administration and configuration.
     Also includes turnkey-occ_ wrapper script (runs occ as www-data user).

     Nextcloud core and bundled apps are root-owned. The web service owns
     config.php and can write its configuration directory so administrator
     settings, scheduled jobs and console commands work. Configuration and
     custom apps are web-writable executable-code boundaries. Install only
     apps and updates you trust.

     **Security note**: Run supervised core updates as ``root`` with
     ``turnkey-nextcloud-update``. The command uses Nextcloud's updater and
     restores the appliance ownership boundary afterwards. See `Nextcloud
     documentation`_ for upgrade planning and backups.

- SSL support out of the box.
- `Adminer`_ administration frontend for MySQL (listening on port
  12322 - uses SSL).
- Postfix MTA (bound to localhost) to allow sending of email (e.g.,
  password recovery).
- Webmin modules for configuring Apache2, PHP, MySQL and Postfix.

Credentials *(passwords set at first boot)*
-------------------------------------------

-  Webmin, SSH, MySQL: username **root**
-  Adminer: username **adminer**
-  Nextcloud: username **admin**

First boot also requests the Nextcloud administrator's recovery email address.
Unattended initial setup requires ``APP_EMAIL`` alongside ``APP_PASS`` and
``APP_DOMAIN``. Re-running setup preserves the existing address unless a new
one is supplied. Configure supported outgoing mail or an SMTP relay in Nextcloud
and verify delivery before relying on password recovery.


.. _Nextcloud: https://nextcloud.com/
.. _TurnKey Core: https://www.turnkeylinux.org/core
.. _occ: https://docs.nextcloud.com/server/stable/admin_manual/configuration_server/occ_command.html
.. _turnkey-occ: https://github.com/turnkeylinux-apps/nextcloud/blob/master/overlay/usr/local/bin/turnkey-occ
.. _Nextcloud documentation: https://docs.nextcloud.com/server/stable/admin_manual/maintenance/upgrade.html
.. _Adminer: https://www.adminer.org
