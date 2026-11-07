#!/bin/bash
set -euo pipefail

result=${TKL_TEST_RESULT:?}
password=${TKL_TEST_APP_PASS:?}
work=/run/tkl-v19-tests/nextcloud
base=https://localhost
curl_args=(-ksS --resolve localhost:443:127.0.0.1)
mkdir -p "$work"

systemctl --quiet is-active apache2.service mariadb.service redis-server.service
grep -q '\[40nextcloud\] successfully completed' /var/log/inithooks.log
curl "${curl_args[@]}" -f "$base/status.php" >"$work/status.json"
python3 -c '
import json, sys
status = json.load(open(sys.argv[1]))
assert status["installed"] is True
assert status["version"].startswith("34.0.5")
' "$work/status.json"

assert_config_writable() {
    local key="turnkey_qa_config_write_$$" actual
    test "$(stat -c '%U:%G:%a' /var/www/nextcloud/config)" = root:www-data:770
    runuser -u www-data -- /usr/bin/php /var/www/nextcloud/occ \
        config:system:set "$key" --value=service-user-config-write
    actual=$(runuser -u www-data -- /usr/bin/php /var/www/nextcloud/occ \
        config:system:get "$key")
    runuser -u www-data -- /usr/bin/php /var/www/nextcloud/occ \
        config:system:delete "$key"
    test "$actual" = service-user-config-write
}
assert_config_writable
runuser -u www-data -- test ! -w /var/www/nextcloud/index.php
runuser -u www-data -- test ! -w /var/www/nextcloud/apps
test "$(stat -c '%U:%G:%a' /var/www/nextcloud/config/config.php)" = www-data:www-data:640
runuser -u www-data -- touch /var/www/nextcloud-data/.tkl-v19-write-test
runuser -u www-data -- rm /var/www/nextcloud-data/.tkl-v19-write-test
runuser -u www-data -- touch /var/www/nextcloud/custom_apps/.tkl-v19-write-test
runuser -u www-data -- rm /var/www/nextcloud/custom_apps/.tkl-v19-write-test

printf 'qa-nextcloud-persistence\n' >"$work/upload.txt"
escaped_auth="admin:$password"
escaped_auth=${escaped_auth//\\/\\\\}
escaped_auth=${escaped_auth//\"/\\\"}
umask 077
printf 'user = "%s"\n' "$escaped_auth" >"$work/curl-auth.conf"
chmod 0600 "$work/curl-auth.conf"
test "$(stat -c '%a' "$work/curl-auth.conf")" = 600
unset escaped_auth
auth_args=(--config "$work/curl-auth.conf")
dav="$base/remote.php/dav/files/admin/qa-v19.txt"
put_status=$(curl "${curl_args[@]}" "${auth_args[@]}" \
    -D "$work/put-headers.txt" -o "$work/put-body.txt" \
    -w '%{http_code}' -T "$work/upload.txt" "$dav")
case "$put_status" in
    201|204) ;;
    *)
        echo "Nextcloud WebDAV PUT failed with HTTP $put_status" >&2
        echo '--- response headers (cookie values redacted) ---' >&2
        sed -E 's/^(Set-Cookie: [^=]+=)[^;]*/\1[REDACTED]/I' \
            "$work/put-headers.txt" >&2
        echo '--- response body (first 16384 bytes) ---' >&2
        head -c 16384 "$work/put-body.txt" >&2
        echo >&2
        echo '--- Nextcloud log (last 65536 bytes) ---' >&2
        tail -c 65536 /var/www/nextcloud-data/nextcloud.log >&2 || true
        echo >&2
        echo '--- Apache error log (last 32768 bytes) ---' >&2
        tail -c 32768 /var/log/apache2/error.log >&2 || true
        echo >&2
        echo '--- Apache access log (last 32768 bytes) ---' >&2
        tail -c 32768 /var/log/apache2/access.log >&2 || true
        exit 22
        ;;
esac
curl "${curl_args[@]}" "${auth_args[@]}" -f "$dav" >"$work/download.txt"
cmp "$work/upload.txt" "$work/download.txt"

turnkey-occ integrity:check-core
assert_scheduled_jobs() {
    # Invoke the actual cron entry point as its configured user; the occ
    # wrapper can otherwise conceal a mismatched config owner.
    grep -Eq '^[^#].*www-data.*php.*nextcloud/cron.php' /etc/cron.d/nextcloud
    before=$(date +%s)
    runuser -u www-data -- /usr/bin/php -f /var/www/nextcloud/cron.php
    last=$(turnkey-occ config:app:get core lastcron)
    test "$last" -ge "$before"
    runuser -u www-data -- /usr/bin/php /var/www/nextcloud/occ status
    assert_config_writable
}
assert_scheduled_jobs
# Exercise the privileged updater's final permissions without changing the
# installed version; normal configuration writes must remain available.
source /usr/local/sbin/turnkey-nextcloud-update
restore_permissions
assert_scheduled_jobs
if runuser -u www-data -- /usr/local/sbin/turnkey-nextcloud-update; then
    echo 'non-root updater invocation unexpectedly succeeded' >&2
    exit 1
fi

systemctl restart mariadb.service redis-server.service apache2.service
curl "${curl_args[@]}" "${auth_args[@]}" -f "$dav" >"$work/after-restart.txt"
cmp "$work/upload.txt" "$work/after-restart.txt"
curl "${curl_args[@]}" "${auth_args[@]}" -f -X DELETE "$dav"
! grep -F -- "$password" /var/log/inithooks.log

cat >"$result" <<EOF
package_source=official Nextcloud 34.0.5 release ZIP pinned by SHA-256
installed_version=34.0.5
runtime_checks=Apache, MariaDB and Redis services, firstboot completion, service-user configuration write/read/delete before and after updater permission restoration, status endpoint, authenticated WebDAV write/read/delete across restart, core integrity, ownership boundaries, configured www-data cron and direct occ execution with persisted lastcron, password log hygiene
updater_command=turnkey-nextcloud-update as root
updater_result=root-only command present; non-root use fails closed; permission restoration preserves service-user configuration writes and scheduled jobs without changing the installed version
updater_channel=official Nextcloud stable releases
integrity_evidence=release ZIP pinned to d077fdca3dc78ef60b5bbc51182f2a1737aa01e2044d6c23f4e7b72146f5239a and turnkey-occ integrity check
EOF
