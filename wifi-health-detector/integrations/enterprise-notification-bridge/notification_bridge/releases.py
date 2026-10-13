from __future__ import absolute_import

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib import request as urllib_request


# Newest-stable DWS version is always resolved live from the official release
# APIs; this constant is never the install target. It is only a trusted floor
# used when every release endpoint is unreachable (offline CI / air-gapped
# host), so the dependency gate still has a safe, conservative value.
TRUSTED_VERSION_FLOOR = "1.0.63"

_SEMVER_BODY = (
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
_SEMVER = re.compile(r"^" + _SEMVER_BODY + r"$")

# Official release-metadata endpoints. Gitee answers quickly inside mainland
# China; GitHub is the authoritative source (its /releases/latest skips betas).
_GITHUB_LATEST = (
    "https://api.github.com/repos/"
    "DingTalk-Real-AI/dingtalk-workspace-cli/releases/latest"
)
_GITEE_LATEST = (
    "https://gitee.com/api/v5/repos/"
    "DingTalk-Real-AI/dingtalk-workspace-cli/releases/latest"
)


def is_stable_semver(version):
    """True for a strict semver string with no prerelease/build suffix."""
    if not isinstance(version, str) or _SEMVER.match(version) is None:
        return False
    return "-" not in version and "+" not in version


def version_key(version):
    """Comparable key for a strict semver value (stable sorts above prerelease)."""
    match = _SEMVER.match(version)
    core = tuple(int(part) for part in match.groups()[:3])
    has_prerelease = "-" in version.split("+", 1)[0]
    return core + (0 if has_prerelease else 1,)


def normalize_tag(tag_name):
    """Extract a stable semver core from a release tag like ``v1.0.63``."""
    if not isinstance(tag_name, str):
        return None
    candidate = tag_name.strip()
    if candidate[:1] in ("v", "V"):
        candidate = candidate[1:]
    return candidate if is_stable_semver(candidate) else None


def stable_version_from_payload(payload):
    """Pull the newest stable version from one release API payload.

    Accepts either a single release object (GitHub/Gitee ``/latest``) or a
    JSON array of releases, ignoring drafts/prereleases.
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return None

    releases = payload if isinstance(payload, list) else [payload]
    best = None
    for item in releases:
        if not isinstance(item, dict):
            continue
        if item.get("draft") is True or item.get("prerelease") is True:
            continue
        version = normalize_tag(item.get("tag_name"))
        if version is None:
            continue
        if best is None or version_key(version) > version_key(best):
            best = version
    return best


def default_urlopener(url, timeout=8):
    """Fetch one release API over HTTPS using only the stdlib."""
    req = urllib_request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/json",
            "User-Agent": "enterprise-notification-bridge",
        },
    )
    with urllib_request.urlopen(req, timeout=timeout) as response:
        status = getattr(response, "status", None)
        if status is not None and status != 200:
            raise RuntimeError("release API returned status %s" % status)
        return response.read()


class LatestVersionResolver(object):
    """Resolve the newest stable DWS release live, China-first, cached."""

    def __init__(self, fetcher=None, cache_ttl=3600, floor=None,
                 gitee_url=None, github_url=None, clock=None):
        self._fetcher = fetcher or default_urlopener
        self._cache_ttl = cache_ttl
        self._floor = floor or TRUSTED_VERSION_FLOOR
        self._gitee_url = gitee_url or _GITEE_LATEST
        self._github_url = github_url or _GITHUB_LATEST
        self._clock = clock or time.time
        self._cached_version = None
        self._cached_at = None

    def latest_stable(self, force_refresh=False):
        """Return the newest stable DWS version.

        Queries both official endpoints and keeps the *highest* stable tag:
        Gitee answers fast in China, but its mirror can lag behind GitHub, so
        a Gitee-only answer must not pin an older release. The result is never
        allowed to drop below the trusted floor.

        When every endpoint fails and the cache is empty, returns the floor
        instead of raising, so dependency setup never hard-blocks.
        """
        now = self._clock()
        if (not force_refresh and self._cached_version is not None
                and self._cached_at is not None
                and now - self._cached_at < self._cache_ttl):
            return self._cached_version

        candidates = []
        # Query both official endpoints concurrently so total latency is the
        # slower single source, not the sum. Gitee answers fast in China;
        # GitHub is authoritative and prevents a lagging Gitee mirror from
        # pinning an older release. Either source failing never blocks setup.
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = {
                executor.submit(self._fetch, url): url
                for url in (self._gitee_url, self._github_url)
            }
            for future in jobs:
                try:
                    version = future.result()
                except Exception:
                    version = None
                if version is not None:
                    candidates.append(version)

        version = max(candidates, key=version_key) if candidates else None
        if version is None or version_key(version) < version_key(self._floor):
            # No trustworthy answer: reuse cache if possible, else the floor.
            if self._cached_version is not None:
                return self._cached_version
            return self._floor

        self._cached_version = version
        self._cached_at = now
        return version

    def _fetch(self, url):
        try:
            return stable_version_from_payload(self._fetcher(url))
        except Exception:
            return None
