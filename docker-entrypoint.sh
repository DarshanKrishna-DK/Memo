#!/bin/sh
# Render mounts persistent disks owned by root; make the media dirs writable for the unprivileged user, then drop root.
set -e
if [ "$(id -u)" = "0" ]; then
  for d in "${STORAGE_DIR:-/app/data/storage}" "${GALLERY_DIR:-/app/data/gallery}"; do
    mkdir -p "$d" && chown -R memo:memo "$d"
  done
  exec setpriv --reuid=memo --regid=memo --init-groups "$@"
fi
exec "$@"
