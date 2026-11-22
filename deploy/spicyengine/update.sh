#!/bin/sh
# Install the current complete release, or replay a saved --pin.
set -eu
set -a
SPICYENGINE_STATE_DIR=/var/lib/spicyengine
SPICYENGINE_PORT=17910
COMPOSE_PROJECT_NAME=spicyengine
. /etc/spicyengine/runtime.env
. /etc/spicyengine/search.env
PYTHONPATH=/opt/spicyengine/congress-current
set +a
runuser -u spicyengine -g spicyengine -G docker -- /opt/spicyengine/congress-prepare/bin/python \
    -m viewer_publication.spicyengine_release --root /srv/spicyengine/input/releases \
    --engine /opt/spicyengine/current/venv/bin/spicyengine --check-query "$SPICYENGINE_READY_QUERY" "$@"
systemctl start spicyengine.service
