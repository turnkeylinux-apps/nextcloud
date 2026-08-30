#!/bin/bash
set -euo pipefail

result=${TKL_TEST_RESULT:?}
password=${TKL_TEST_APP_PASS:?}
work=/run/tkl-v19-tests/nextcloud
base=https://localhost
curl_args=(-ksS --resolve localhost:443:127.0.0.1)
mkdir -p "$work"

diagnostic_state=/run/tkl-nextcloud-auth-state
trap 'rm -f -- "$diagnostic_state"' EXIT

systemctl --quiet is-active apache2.service mariadb.service redis-server.service
grep -q '\[40nextcloud\] successfully completed' /var/log/inithooks.log
curl "${curl_args[@]}" -f "$base/status.php" >"$work/status.json"
python3 -c '
import json, sys
status = json.load(open(sys.argv[1]))
assert status["installed"] is True
assert status["version"].startswith("34.0.0")
' "$work/status.json"

readonly_conf=/var/www/nextcloud/config/turnkey-read-only.config.php
assert_config_read_only() {
    runuser -u www-data -- /usr/bin/php -r '
$CONFIG = array();
require "/var/www/nextcloud/config/turnkey-read-only.config.php";
exit(($CONFIG["config_is_read_only"] ?? false) === true ? 0 : 1);
'
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
escaped_auth="admin:$password"
escaped_auth=${escaped_auth//\\/\\\\}
escaped_auth=${escaped_auth//\"/\\\"}
umask 077
printf 'user = "%s"\n' "$escaped_auth" >"$work/curl-auth.conf"
chmod 0600 "$work/curl-auth.conf"
test "$(stat -c '%a' "$work/curl-auth.conf")" = 600
unset escaped_auth
auth_args=(--config "$work/curl-auth.conf")

# Temporary acceptance trace: compare keyed fingerprints only. These booleans
# distinguish post-firstboot mutation from a runtime credential mismatch.
. "$diagnostic_state"
fingerprint() {
    openssl dgst -sha256 -mac HMAC -macopt "hexkey:$diagnostic_key" -r |
        awk '{print $1}'
}
runtime_password_fingerprint=$(printf '%s' "$password" | fingerprint)
runtime_password_matches_firstboot=false
if test "$runtime_password_fingerprint" = \
        "$firstboot_password_fingerprint"; then
    runtime_password_matches_firstboot=true
fi
runtime_hash=$(
    runuser -u www-data -- /usr/bin/php -r '
define("OC_CONSOLE", 1);
require_once "/var/www/nextcloud/lib/base.php";
$user = \OCP\Server::get(\OCP\IUserManager::class)->get("admin");
echo $user?->getPasswordHash() ?? "";
'
)
runtime_hash_fingerprint=$(printf '%s' "$runtime_hash" | fingerprint)
runtime_hash_matches_firstboot=false
if test "$runtime_hash_fingerprint" = "$firstboot_hash_fingerprint"; then
    runtime_hash_matches_firstboot=true
fi
printf 'runtime_password_matches_firstboot=%s\n' \
    "$runtime_password_matches_firstboot"
printf 'runtime_hash_matches_firstboot=%s\n' \
    "$runtime_hash_matches_firstboot"
unset diagnostic_key firstboot_password_fingerprint \
    firstboot_hash_fingerprint runtime_password_fingerprint runtime_hash \
    runtime_hash_fingerprint
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
curl "${curl_args[@]}" "${auth_args[@]}" -f "$dav" >"$work/after-restart.txt"
cmp "$work/upload.txt" "$work/after-restart.txt"
curl "${curl_args[@]}" "${auth_args[@]}" -f -X DELETE "$dav"
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
