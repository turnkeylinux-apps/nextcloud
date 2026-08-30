#!/bin/bash
set -euo pipefail

result=${TKL_TEST_RESULT:?}
password=${TKL_TEST_APP_PASS:?}
work=/run/tkl-v19-tests/nextcloud
base=https://localhost
curl_args=(-kfsS --resolve localhost:443:127.0.0.1)
mkdir -p "$work"

systemctl --quiet is-active apache2.service mariadb.service redis-server.service
grep -q '\[40nextcloud\] successfully completed' /var/log/inithooks.log
curl "${curl_args[@]}" "$base/status.php" >"$work/status.json"
python3 -c '
import json, sys
status = json.load(open(sys.argv[1]))
assert status["installed"] is True
assert status["version"].startswith("34.0.0")
' "$work/status.json"

readonly_conf=/var/www/nextcloud/config/turnkey-read-only.config.php
assert_config_read_only() {
    case "$(turnkey-occ config:system:get config_is_read_only)" in
        true|1) ;;
        *) echo 'Nextcloud read-only configuration is not effective' >&2; return 1 ;;
    esac
}
assert_config_read_only
test "$(stat -c '%U:%G:%a' "$readonly_conf")" = root:www-data:640
runuser -u www-data -- test ! -w /var/www/nextcloud/index.php
runuser -u www-data -- test ! -w /var/www/nextcloud/config/config.php
runuser -u www-data -- test ! -w "$readonly_conf"
runuser -u www-data -- touch /var/www/nextcloud-data/.tkl-v19-write-test
runuser -u www-data -- rm /var/www/nextcloud-data/.tkl-v19-write-test
runuser -u www-data -- touch /var/www/nextcloud/custom_apps/.tkl-v19-write-test
runuser -u www-data -- rm /var/www/nextcloud/custom_apps/.tkl-v19-write-test

printf 'qa-nextcloud-persistence\n' >"$work/upload.txt"
printf 'machine localhost login admin password %s\n' "$password" >"$work/netrc"
chmod 0600 "$work/netrc"
dav="$base/remote.php/dav/files/admin/qa-v19.txt"
curl "${curl_args[@]}" --netrc-file "$work/netrc" -T "$work/upload.txt" "$dav"
curl "${curl_args[@]}" --netrc-file "$work/netrc" "$dav" >"$work/download.txt"
cmp "$work/upload.txt" "$work/download.txt"

turnkey-occ integrity:check-core
# Exercise the same atomic read-only toggle used by the privileged updater
# without contacting the update service or changing the installed version.
source /usr/local/sbin/turnkey-nextcloud-update
trap restore_read_only_config EXIT
disable_read_only_config
test ! -e "$READ_ONLY_CONF"
test "$(stat -c '%U:%G:%a' "$READ_ONLY_CONF_DISABLED")" = \
    root:www-data:640
restore_read_only_config
trap - EXIT
test ! -e "$READ_ONLY_CONF_DISABLED"
test "$(stat -c '%U:%G:%a' "$readonly_conf")" = root:www-data:640
assert_config_read_only
if runuser -u www-data -- /usr/local/sbin/turnkey-nextcloud-update; then
    echo 'non-root updater invocation unexpectedly succeeded' >&2
    exit 1
fi

systemctl restart mariadb.service redis-server.service apache2.service
curl "${curl_args[@]}" --netrc-file "$work/netrc" "$dav" >"$work/after-restart.txt"
cmp "$work/upload.txt" "$work/after-restart.txt"
curl "${curl_args[@]}" --netrc-file "$work/netrc" -X DELETE "$dav"
! grep -F -- "$password" /var/log/inithooks.log

cat >"$result" <<EOF
package_source=official Nextcloud 34.0.0 release ZIP pinned by SHA-256
installed_version=34.0.0
runtime_checks=Apache, MariaDB and Redis services, firstboot completion, read-only merged configuration and updater toggle, status endpoint, authenticated WebDAV write/read/delete across restart, core integrity, ownership boundaries, password log hygiene
updater_command=turnkey-nextcloud-update as root
updater_result=root-only command present; non-root use fails closed; atomic read-only fragment disable and restore validated without changing the installed version
updater_channel=official Nextcloud stable releases
integrity_evidence=release ZIP pinned to e6e0f29026abb8373e12e4c1cdb1ac4d0405faacbdbdf9b86263de06daeaae57 and turnkey-occ integrity check
EOF
