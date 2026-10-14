from __future__ import absolute_import

import json
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.releases import (
    TRUSTED_VERSION_FLOOR,
    LatestVersionResolver,
    is_stable_semver,
    normalize_tag,
    stable_version_from_payload,
    version_key,
)


GITEE = "https://gitee.example/latest"
GITHUB = "https://api.github.example/latest"


class FakeClock(object):
    def __init__(self, start=1000.0):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class RecordingFetcher(object):
    def __init__(self, by_url=None, failing_urls=None, payloads_raw=None):
        self.by_url = dict(by_url or {})
        self.failing_urls = set(failing_urls or [])
        self.payloads_raw = dict(payloads_raw or {})
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url in self.failing_urls:
            raise RuntimeError("network unavailable: " + url)
        if url in self.payloads_raw:
            return self.payloads_raw[url]
        return json.dumps(self.by_url.get(url)).encode("utf-8")


def release(tag, prerelease=False, draft=False):
    return {
        "tag_name": tag, "prerelease": prerelease, "draft": draft,
        "name": tag,
    }


class SemverTests(unittest.TestCase):
    def test_is_stable_semver(self):
        self.assertTrue(is_stable_semver("1.0.63"))
        self.assertTrue(is_stable_semver("2.10.0"))
        self.assertFalse(is_stable_semver("1.0.63-beta.1"))
        self.assertFalse(is_stable_semver("1.0.63+build.2"))
        self.assertFalse(is_stable_semver("v1.0.63"))
        self.assertFalse(is_stable_semver("1.0"))
        self.assertFalse(is_stable_semver(None))

    def test_normalize_tag_strips_v_prefix(self):
        self.assertEqual(normalize_tag("v1.0.63"), "1.0.63")
        self.assertEqual(normalize_tag("V1.0.63"), "1.0.63")
        self.assertEqual(normalize_tag("  v1.2.3  "), "1.2.3")

    def test_normalize_tag_rejects_prerelease_and_garbage(self):
        self.assertIsNone(normalize_tag("v1.0.64-beta.1"))
        self.assertIsNone(normalize_tag("latest"))
        self.assertIsNone(normalize_tag(None))

    def test_version_key_orders_semver(self):
        self.assertLess(version_key("1.0.60"), version_key("1.0.63"))
        self.assertLess(version_key("1.0.63"), version_key("1.1.0"))
        self.assertLess(version_key("1.0.63-rc.1"), version_key("1.0.63"))


class PayloadParsingTests(unittest.TestCase):
    def test_single_latest_object(self):
        payload = release("v1.0.63")
        self.assertEqual(stable_version_from_payload(payload), "1.0.63")

    def test_list_picks_highest_stable_ignoring_beta_and_draft(self):
        payload = [
            release("v1.0.64-beta.1", prerelease=True),
            release("v1.0.63"),
            release("v1.0.63-beta.3", prerelease=True),
            release("v1.0.62"),
        ]
        self.assertEqual(stable_version_from_payload(payload), "1.0.63")

    def test_draft_release_is_ignored(self):
        payload = [release("v1.0.99", draft=True), release("v1.0.63")]
        self.assertEqual(stable_version_from_payload(payload), "1.0.63")

    def test_only_prereleases_returns_none(self):
        payload = [release("v1.0.64-beta.1", prerelease=True)]
        self.assertIsNone(stable_version_from_payload(payload))

    def test_accepts_json_string_and_bytes(self):
        text = json.dumps(release("v1.0.63"))
        self.assertEqual(stable_version_from_payload(text), "1.0.63")
        self.assertEqual(
            stable_version_from_payload(text.encode("utf-8")), "1.0.63"
        )

    def test_invalid_json_returns_none(self):
        self.assertIsNone(stable_version_from_payload("not json"))
        self.assertIsNone(stable_version_from_payload(123))
        self.assertIsNone(stable_version_from_payload([None]))


class LatestVersionResolverTests(unittest.TestCase):
    def resolver(self, fetcher, floor=TRUSTED_VERSION_FLOOR, ttl=3600):
        return LatestVersionResolver(
            fetcher=fetcher, cache_ttl=ttl, floor=floor,
            gitee_url=GITEE, github_url=GITHUB, clock=FakeClock(),
        )

    def test_github_authoritative_beats_lagging_gitee(self):
        fetcher = RecordingFetcher({
            GITEE: release("v1.0.60"),
            GITHUB: release("v1.0.63"),
        })
        resolver = self.resolver(fetcher)
        self.assertEqual(resolver.latest_stable(), "1.0.63")

    def test_newer_gitee_tag_is_accepted_when_github_is_slower(self):
        fetcher = RecordingFetcher({
            GITEE: release("v1.1.0"),
            GITHUB: release("v1.0.63"),
        })
        resolver = self.resolver(fetcher)
        self.assertEqual(resolver.latest_stable(), "1.1.0")

    def test_both_sources_fail_returns_floor(self):
        fetcher = RecordingFetcher(failing_urls=(GITEE, GITHUB))
        resolver = self.resolver(fetcher, floor="1.0.63")
        self.assertEqual(resolver.latest_stable(), "1.0.63")

    def test_failed_sources_reuse_fresh_cache(self):
        good = RecordingFetcher({
            GITEE: release("v1.0.60"), GITHUB: release("v1.0.63"),
        })
        resolver = self.resolver(good)
        self.assertEqual(resolver.latest_stable(), "1.0.63")
        # Endpoints now fail; the cached answer must survive within its TTL.
        dead = RecordingFetcher(failing_urls=(GITEE, GITHUB))
        resolver._fetcher = dead
        self.assertEqual(resolver.latest_stable(force_refresh=True), "1.0.63")

    def test_expired_cache_falls_back_to_floor_when_sources_die(self):
        clock = FakeClock()
        good = RecordingFetcher({
            GITEE: release("v1.0.60"), GITHUB: release("v1.0.63"),
        })
        resolver = LatestVersionResolver(
            fetcher=good, cache_ttl=10, floor="1.0.63",
            gitee_url=GITEE, github_url=GITHUB, clock=clock,
        )
        self.assertEqual(resolver.latest_stable(), "1.0.63")
        clock.advance(11)
        resolver._fetcher = RecordingFetcher(failing_urls=(GITEE, GITHUB))
        self.assertEqual(resolver.latest_stable(), "1.0.63")

    def test_result_below_floor_is_rejected(self):
        fetcher = RecordingFetcher({
            GITEE: release("v1.0.50"), GITHUB: release("v1.0.60"),
        })
        resolver = self.resolver(fetcher, floor="1.0.63")
        self.assertEqual(resolver.latest_stable(), "1.0.63")

    def test_cache_avoids_repeat_fetches_within_ttl(self):
        fetcher = RecordingFetcher({
            GITEE: release("v1.0.63"), GITHUB: release("v1.0.63"),
        })
        resolver = self.resolver(fetcher)
        resolver.latest_stable()
        resolver.latest_stable()
        resolver.latest_stable()
        self.assertEqual(len(fetcher.calls), 2)

    def test_force_refresh_hits_sources_again(self):
        fetcher = RecordingFetcher({
            GITEE: release("v1.0.63"), GITHUB: release("v1.0.63"),
        })
        resolver = self.resolver(fetcher)
        resolver.latest_stable()
        resolver.latest_stable(force_refresh=True)
        self.assertEqual(len(fetcher.calls), 4)

    def test_resolver_never_raises_on_bad_fetcher_output(self):
        fetcher = RecordingFetcher(payloads_raw={
            GITEE: b"garbage", GITHUB: b"<html>502</html>",
        })
        resolver = self.resolver(fetcher, floor="1.0.63")
        self.assertEqual(resolver.latest_stable(), "1.0.63")

    def test_floor_matches_static_dependency_constant(self):
        # The offline static gate and the resolver's all-endpoints-failed
        # fallback must advertise the same conservative version.
        from notification_bridge.dependencies import MINIMUM_DWS_VERSION
        self.assertEqual(TRUSTED_VERSION_FLOOR, MINIMUM_DWS_VERSION)


class LatestVersionResolverLoggingTests(unittest.TestCase):
    def _resolver(self, fetcher, events, **kwargs):
        return LatestVersionResolver(
            fetcher=fetcher, floor="1.0.63",
            gitee_url=GITEE, github_url=GITHUB, clock=FakeClock(),
            logger=lambda event, **details: events.append((event, details)),
            **kwargs,
        )

    def test_logs_resolved_and_per_source_events(self):
        events = []
        fetcher = RecordingFetcher({
            GITEE: release("v1.0.60"), GITHUB: release("v1.0.63"),
        })
        resolver = self._resolver(fetcher, events)
        resolver.latest_stable()
        names = [name for name, _ in events]
        self.assertIn("resolved", names)
        ok_sources = {details["source"] for name, details in events
                      if name == "source_ok"}
        self.assertEqual(ok_sources, {"gitee", "github"})
        resolved = [details for name, details in events
                    if name == "resolved"][0]
        self.assertEqual(resolved["version"], "1.0.63")
        self.assertEqual(resolved["sources"], 2)

    def test_logs_source_failed_then_floor_fallback(self):
        events = []
        fetcher = RecordingFetcher(failing_urls=(GITEE, GITHUB))
        resolver = self._resolver(fetcher, events)
        resolver.latest_stable()
        names = [name for name, _ in events]
        self.assertEqual(names.count("source_failed"), 2)
        self.assertEqual(names[-1], "floor_fallback")
        self.assertEqual(events[-1][1]["version"], "1.0.63")

    def test_logs_cache_hit_on_second_call(self):
        events = []
        fetcher = RecordingFetcher({
            GITEE: release("v1.0.63"), GITHUB: release("v1.0.63"),
        })
        resolver = self._resolver(fetcher, events)
        resolver.latest_stable()
        resolver.latest_stable()
        self.assertEqual(events[-1], ("cache_hit", {"version": "1.0.63"}))

    def test_logger_exception_never_breaks_resolution(self):
        def broken_logger(event, **details):
            raise RuntimeError("logger broken")
        fetcher = RecordingFetcher({
            GITEE: release("v1.0.63"), GITHUB: release("v1.0.63"),
        })
        resolver = LatestVersionResolver(
            fetcher=fetcher, floor="1.0.63",
            gitee_url=GITEE, github_url=GITHUB, clock=FakeClock(),
            logger=broken_logger,
        )
        self.assertEqual(resolver.latest_stable(), "1.0.63")


if __name__ == "__main__":
    unittest.main()
