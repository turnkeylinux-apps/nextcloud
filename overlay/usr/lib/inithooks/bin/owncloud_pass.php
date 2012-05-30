<?php

include '/var/www/owncloud/3rdparty/phpass/PasswordHash.php';

if(count($argv)!=2) die("usage: $argv[0] password\n");

$password = $argv[1];

$PasswordHash = new PasswordHash(8, false);
print $PasswordHash->HashPassword($password);

?>

