from __future__ import absolute_import

import re


# Single semantic-version grammar shared by dependency verification
# (dependencies.py) and live release resolution (releases.py). Keeping one
# body here prevents the two strict-semver implementations from drifting.
SEMVER_BODY = (
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
SEMVER = re.compile(r"^" + SEMVER_BODY + r"$")

# Minimum DWS release the bridge will accept, and also the trusted floor used
# by the live resolver when every release endpoint is unreachable. These were
# previously two identical constants kept in sync only by a test; they are the
# same operational value by definition (nothing older than the gate may be
# installed), so they now have one source.
MINIMUM_DWS_VERSION = "1.0.63"
TRUSTED_VERSION_FLOOR = MINIMUM_DWS_VERSION


def semver_key(version):
    """Comparable key for a strict semver value (stable sorts above prerelease).

    Callers must first validate the value with their own policy
    (:func:`releases.is_stable_semver` or the dependency gate's strict check).
    """
    match = SEMVER.match(version)
    core = tuple(int(part) for part in match.groups()[:3])
    has_prerelease = "-" in version.split("+", 1)[0]
    return core + (0 if has_prerelease else 1,)
