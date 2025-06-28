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

--------------------------------------------

For updating the version of nextcloud you should check for the version upstream (stable or beta) This can be done in the Administration page of NC or in the /var/www/nextcloud/config/config.php file

By the interface you should change the /etc/php/{your_current_version}/cli/php.ini and /etc/php/{your_current_version}/apache/php.ini max execution time to be able to download the files.

You can also update by the terminal following this steps
.. code-block:: bash

    $ su -l www-data -s /bin/bash

    $ cd /var/www/nextcloud/updater

    $ php updater.phar

When asked:

Should the "occ upgrade" command be executed? [Y/n] 

Yes is Highly recomended

For more info about this matter check the updater `documentation <https://docs.nextcloud.com/server/latest/admin_manual/maintenance/update.html>`_.
