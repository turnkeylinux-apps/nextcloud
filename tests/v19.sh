#!/bin/bash
set -euo pipefail

result=${TKL_TEST_RESULT:?}
password=${TKL_TEST_APP_PASS:?}
work=/run/tkl-v19-tests/nextcloud
base=https://localhost
curl_args=(-ksS --resolve localhost:443:127.0.0.1)
mkdir -p "$work"

auth_probe=/var/www/nextcloud/tkl-v19-auth-probe.php
debug_conf=/var/www/nextcloud/config/tkl-v19-debug.config.php
app_probe=$work/nextcloud-auth-probe.php
diagnostic_cleanup() {
    rm -f -- "$auth_probe" "$debug_conf" "$app_probe" \
        "$work/curl-auth.conf"
    unset probe_key probe_password_hmac escaped_auth
}
trap diagnostic_cleanup EXIT

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

# Diagnose the complete HTTP/PHP credential boundary without returning or
# persisting the credential. The endpoint contains only an ephemeral HMAC key
# and digest, emits booleans only, and is deleted by the EXIT trap.
probe_key=$(openssl rand -hex 32)
probe_password_hmac=$(
    {
        printf '%s\n' "$probe_key"
        printf '%s' "$password"
    } | python3 -c '
import hashlib
import hmac
import sys
key = bytes.fromhex(sys.stdin.buffer.readline().strip().decode())
password = sys.stdin.buffer.read()
print(hmac.new(key, password, hashlib.sha256).hexdigest())
'
)
install -o root -g www-data -m 0640 /dev/stdin "$auth_probe" <<'PHP'
<?php
header('Content-Type: application/json');
$authorization = $_SERVER['HTTP_AUTHORIZATION']
    ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION']
    ?? '';
$decoded = '';
if (str_starts_with($authorization, 'Basic ')) {
    $decoded = base64_decode(substr($authorization, 6), true) ?: '';
}
[$decodedUser, $decodedPassword] = array_pad(explode(':', $decoded, 2), 2, '');
$passwordHmac = hash_hmac('sha256', $decodedPassword, hex2bin('PROBE_KEY'));
echo json_encode([
    'basic_header_present' => str_starts_with($authorization, 'Basic '),
    'decoded_username_is_admin' => hash_equals('admin', $decodedUser),
    'decoded_password_is_expected' => hash_equals('PROBE_PASSWORD_HMAC', $passwordHmac),
    'php_auth_user_equals_decoded' => isset($_SERVER['PHP_AUTH_USER'])
        && hash_equals($decodedUser, $_SERVER['PHP_AUTH_USER']),
    'php_auth_password_equals_decoded' => isset($_SERVER['PHP_AUTH_PW'])
        && hash_equals($decodedPassword, $_SERVER['PHP_AUTH_PW']),
], JSON_THROW_ON_ERROR);
PHP
sed -i \
    -e "s/PROBE_KEY/$probe_key/" \
    -e "s/PROBE_PASSWORD_HMAC/$probe_password_hmac/" \
    "$auth_probe"
chown root:www-data "$auth_probe"
chmod 0640 "$auth_probe"
unset probe_key probe_password_hmac
curl "${curl_args[@]}" "${auth_args[@]}" -f \
    "$base/tkl-v19-auth-probe.php" >"$work/apache-auth.json"
python3 -c '
import json, sys
result = json.load(open(sys.argv[1]))
assert set(result) == {
    "basic_header_present",
    "decoded_username_is_admin",
    "decoded_password_is_expected",
    "php_auth_user_equals_decoded",
    "php_auth_password_equals_decoded",
}
assert all(isinstance(value, bool) for value in result.values())
' "$work/apache-auth.json"
echo 'Apache/PHP Basic authentication boundary:'
cat "$work/apache-auth.json"
echo

# Raise Nextcloud logging for this disposable run only. The fragment is never
# part of the appliance result and is removed by the EXIT trap.
install -o root -g www-data -m 0640 /dev/stdin "$debug_conf" <<'EOF'
<?php
$CONFIG = array(
    'loglevel' => 0,
);
EOF

# Compare application-level state using stdin-only password input and emit
# booleans only. In particular, distinguish backend acceptance from account,
# token-only, two-factor and token-collision policy.
install -o root -g www-data -m 0640 /dev/stdin "$app_probe" <<'PHP'
<?php
define("OC_CONSOLE", 1);
require_once "/var/www/nextcloud/lib/base.php";
$password = rtrim(stream_get_contents(STDIN), "\r\n");
$manager = \OCP\Server::get(\OCP\IUserManager::class);
$user = $manager->get("admin");
$accepted = $manager->checkPassword("admin", $password) !== false;
$tokenCollision = false;
try {
    \OCP\Server::get(\OC\Authentication\Token\IProvider::class)->getToken($password);
    $tokenCollision = true;
} catch (\OCP\Authentication\Exceptions\ExpiredTokenException) {
    $tokenCollision = true;
} catch (\OCP\Authentication\Exceptions\InvalidTokenException) {
}
$twoFactor = $user === null ? false : \OCP\Server::get(
    \OC\Authentication\TwoFactorAuth\Manager::class
)->isTwoFactorAuthenticated($user);
echo json_encode([
    "backend_password_accepted" => $accepted,
    "user_exists" => $user !== null,
    "user_enabled" => $user !== null && $user->isEnabled(),
    "token_auth_enforced" => \OCP\Server::get(\OCP\IConfig::class)
        ->getSystemValueBool("token_auth_enforced", false),
    "two_factor_enforced" => $twoFactor,
    "token_collision" => $tokenCollision,
], JSON_THROW_ON_ERROR);
PHP
printf '%s\n' "$password" | runuser -u www-data -- /usr/bin/php "$app_probe" \
    >"$work/nextcloud-auth.json"
python3 -c '
import json, sys
result = json.load(open(sys.argv[1]))
assert set(result) == {
    "backend_password_accepted",
    "user_exists",
    "user_enabled",
    "token_auth_enforced",
    "two_factor_enforced",
    "token_collision",
}
assert all(isinstance(value, bool) for value in result.values())
' "$work/nextcloud-auth.json"
echo 'Nextcloud authentication state:'
cat "$work/nextcloud-auth.json"
echo
rm -f -- "$auth_probe" "$app_probe"

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
        {
            printf '%s\n' "$password"
            head -c 16384 "$work/put-body.txt"
        } | python3 -c '
import sys
secret = sys.stdin.buffer.readline().rstrip(b"\r\n")
body = sys.stdin.buffer.read()
sys.stdout.buffer.write(body.replace(secret, b"[REDACTED]"))
' >&2
        echo >&2
        echo '--- Nextcloud log (last 65536 bytes) ---' >&2
        {
            printf '%s\n' "$password"
            tail -c 65536 /var/www/nextcloud-data/nextcloud.log || true
        } | python3 -c '
import sys
secret = sys.stdin.buffer.readline().rstrip(b"\r\n")
body = sys.stdin.buffer.read()
sys.stdout.buffer.write(body.replace(secret, b"[REDACTED]"))
' >&2
        echo >&2
        echo '--- Apache error log (last 32768 bytes) ---' >&2
        {
            printf '%s\n' "$password"
            tail -c 32768 /var/log/apache2/error.log || true
        } | python3 -c '
import sys
secret = sys.stdin.buffer.readline().rstrip(b"\r\n")
body = sys.stdin.buffer.read()
sys.stdout.buffer.write(body.replace(secret, b"[REDACTED]"))
' >&2
        echo >&2
        echo '--- Apache access log (last 32768 bytes) ---' >&2
        {
            printf '%s\n' "$password"
            tail -c 32768 /var/log/apache2/access.log || true
        } | python3 -c '
import sys
secret = sys.stdin.buffer.readline().rstrip(b"\r\n")
body = sys.stdin.buffer.read()
sys.stdout.buffer.write(body.replace(secret, b"[REDACTED]"))
' >&2
        exit 22
        ;;
esac
rm -f -- "$debug_conf"
curl "${curl_args[@]}" "${auth_args[@]}" -f "$dav" >"$work/download.txt"
cmp "$work/upload.txt" "$work/download.txt"

turnkey-occ integrity:check-core
# Exercise the same atomic read-only toggle used by the privileged updater
# without contacting the update service or changing the installed version.
source /usr/local/sbin/turnkey-nextcloud-update
trap 'restore_read_only_config; diagnostic_cleanup' EXIT
disable_read_only_config
test ! -e "$READ_ONLY_CONF"
test "$(stat -c '%U:%G:%a' "$READ_ONLY_CONF_DISABLED")" = \
    root:www-data:640
restore_read_only_config
trap diagnostic_cleanup EXIT
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
