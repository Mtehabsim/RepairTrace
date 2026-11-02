#!/bin/bash
# Called inside a fresh user/mount/network/PID namespace. No host project tree is mounted.
set -euo pipefail
root=$1
repo=$2
venv=$3
python_prefix=$4
evidence=$5
command_text=$6
mount --make-rprivate /
bind_ro() {
  mount --rbind "$1" "$2"
  mount -o remount,bind,ro "$2"
}
bind_ro /usr "$root/usr"
for part in lib lib64; do
  if [ -d "/$part" ] && [ ! -L "$root/$part" ]; then bind_ro "/$part" "$root/$part"; fi
done
bind_ro "$python_prefix" "$root$python_prefix"
bind_ro "$venv" "$root/env"
bind_ro "$evidence" "$root/evidence"
bind_ro "$repo" "$root/work"
mount -t tmpfs -o size=512m tmpfs "$root/tmp"
mount --rbind /dev "$root/dev"
touch "$root/tmp/empty-device"
for entry in "$root/dev/"*; do
  name=${entry##*/}
  case "$name" in null|zero|random|urandom) continue ;; esac
  if [ -L "$entry" ]; then continue; fi
  if [ -d "$entry" ]; then
    mount -t tmpfs -o ro,size=1m tmpfs "$entry"
  else
    mount --bind "$root/tmp/empty-device" "$entry"
    mount -o remount,bind,ro "$entry"
  fi
done
mount -o remount,bind,ro "$root/dev"
exec chroot "$root" /usr/bin/setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs \
  /usr/bin/env -i PATH=/env/bin:/usr/bin:/bin HOME=/tmp TMPDIR=/tmp \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 MPLBACKEND=Agg \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  /bin/bash --noprofile --norc -c 'cd /work; eval "$1"' sandbox "$command_text"
