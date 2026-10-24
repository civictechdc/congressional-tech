"""Canonical publication and preflight constants."""
from __future__ import annotations

BUCKET = 'congressional-tech-raw'
PREFIX = 'viewer-publications/'
PUBLIC_URL = 'https://congressional-data.spicygov.ai/viewer-publications/'
PUBLISHER_VERSION = 10
USER_AGENT = 'congressional-tech-viewer-publisher/1.0 (+https://github.com/civictechdc/congressional-tech)'
ACCEPTED_KEY = PREFIX + 'recoveries/accepted.json'
LIMITS = {'manifest': 4 * 1024**2, 'accepted': 16 * 1024**2, 'recovery': 32 * 1024**2}
