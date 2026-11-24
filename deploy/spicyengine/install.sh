#!/bin/sh
# Install the producer from an identified checkout or git archive on a Linux search host.
set -eu
assets=$(dirname "$(realpath "$0")")
checkout=$(realpath "$assets/../..")
revision=${1:-$(git -C "$checkout" rev-parse HEAD)}
case "$revision" in *[!a-f0-9]* | '') echo 'Expected a Git revision' >&2; exit 1;; esac
[ "${#revision}" -eq 40 ] || exit 1
target="/opt/spicyengine/congress-releases/$revision"
runtime=/opt/spicyengine/congress-prepare
getent passwd spicyengine >/dev/null || useradd --system --home-dir /var/lib/spicyengine --shell /usr/sbin/nologin spicyengine
install -d "$target" /etc/spicyengine /usr/local/sbin
install -d -o spicyengine -g spicyengine -m 0755 /srv/spicyengine/input/releases
if ! "$runtime/bin/python" -c 'import duckdb,pyarrow; assert (duckdb.__version__,pyarrow.__version__)==("1.5.5","25.0.1")' 2>/dev/null; then
    python3.12 -m venv "$runtime"
    "$runtime/bin/pip" install --disable-pip-version-check duckdb==1.5.5 pyarrow==25.0.1
fi
if [ ! -f "$target/installed" ]; then
    for package in congress_api congress_shared viewer_publication; do
        cp -R "$checkout/packages/$package/src/$package" "$target/"
    done
    PYTHONPATH="$target" "$runtime/bin/python" -m viewer_publication.spicyengine_release --help >/dev/null
    touch "$target/installed"
fi
ln -sfn "$target" /opt/spicyengine/congress-current.next
mv -Tf /opt/spicyengine/congress-current.next /opt/spicyengine/congress-current
install -m 0644 "$assets/search.env" /etc/spicyengine/search.env
install -m 0755 "$assets/update.sh" /usr/local/sbin/spicyengine-update
install -m 0644 "$assets/spicyengine-update.service" "$assets/spicyengine-update.timer" /etc/systemd/system/
systemctl daemon-reload
