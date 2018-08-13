Nextcloud - Share files, music, calendar
========================================

`Nextcloud`_ helps store your files, folders, contacts, photo galleries,
calendars and more on a server of your choosing. Access that folder from
your mobile device, your desktop, or a web browser. Access your data
wherever you are, when you need it.

This appliance includes all the standard features in `TurnKey Core`_,
and on top of that:

- Nextcloud Server:
   
   - Installed from official zip file. No automatic updates.

     **Security note**: Updates to Nextcloud may require supervision so
     they **ARE NOT** configured to install automatically. See `Nextcloud
     documentation`_ for upgrading.

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


.. _Nextcloud: https://nextcloud.com/
.. _TurnKey Core: https://www.turnkeylinux.org/core
.. _Nextcloud documentation: https://docs.nextcloud.com/server/13/admin_manual/maintenance/upgrade.html
.. _Adminer: https://www.adminer.org
