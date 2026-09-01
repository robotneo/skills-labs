from __future__ import absolute_import

from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import sqlite3
import uuid


class DeliveryKey(namedtuple(
        "DeliveryKeyBase", "report_id platform provider profile recipient")):
    __slots__ = ()


class Claim(namedtuple("ClaimBase", "key claim_id acquired reason")):
    __slots__ = ()


Claim.__new__.__defaults__ = ("",)


class DeliveryLedger(object):
    """A local, metadata-only record of notification delivery attempts."""

    _STATES = (
        "claimed", "succeeded", "retryable_failure", "permanent_failure",
    )

    def __init__(self, path, lease_seconds=300, clock=None):
        self.path = path
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)):
            raise ValueError("lease_seconds must be numeric")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.lease_seconds = float(lease_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._create_schema()
        self._secure_file()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, mode="DEFERRED"):
        if mode not in ("DEFERRED", "IMMEDIATE", "EXCLUSIVE"):
            raise ValueError("unsupported transaction mode")
        with self.connection() as connection:
            connection.execute("BEGIN {0}".format(mode))
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def claim(self, key):
        with self.transaction("IMMEDIATE") as connection:
            row = self._get_row(connection, key)
            if row and row["state"] == "claimed":
                reason = ("delivery_reconciliation_required"
                          if self._claim_expired(row) else "delivery_in_progress")
                return Claim(key, row["claim_id"], False, reason)
            if row and row["state"] == "succeeded":
                return Claim(
                    key, row["claim_id"], False, "delivery_already_succeeded"
                )
            if row and row["state"] == "permanent_failure":
                return Claim(
                    key, row["claim_id"], False, "delivery_permanently_failed"
                )

            claim_id = uuid.uuid4().hex
            self._upsert_claim(connection, key, claim_id)
            return Claim(key, claim_id, True, "")

    def mark_success(self, claim, external_id=""):
        return self._finish(claim, "succeeded", "", False, external_id)

    def mark_failure(self, claim, reason, retryable):
        state = "retryable_failure" if retryable else "permanent_failure"
        return self._finish(claim, state, reason, retryable, "")

    def get(self, key):
        with self.connection() as connection:
            return self._get_row(connection, key)

    def _create_schema(self):
        with self.connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS delivery_ledger (
                    report_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN (
                        'claimed', 'succeeded', 'retryable_failure',
                        'permanent_failure'
                    )),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
                    external_id TEXT NOT NULL,
                    PRIMARY KEY (report_id, platform, provider, profile, recipient)
                )
            """)

    def _claim_expired(self, row):
        try:
            updated_at = datetime.strptime(
                row["updated_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return True
        return (self._now() - updated_at).total_seconds() > self.lease_seconds

    def _secure_file(self):
        if self.path == ":memory:":
            return
        try:
            os.chmod(self.path, 0o600)
        except (AttributeError, OSError):
            pass

    def _finish(self, claim, state, reason, retryable, external_id):
        if state not in self._STATES:
            raise ValueError("unsupported delivery state")
        with self.transaction("IMMEDIATE") as connection:
            cursor = connection.execute("""
                UPDATE delivery_ledger
                SET state = ?, updated_at = ?, reason = ?, retryable = ?, external_id = ?
                WHERE report_id = ? AND platform = ? AND provider = ?
                  AND profile = ? AND recipient = ? AND claim_id = ?
                  AND state = 'claimed'
            """, (
                state, self._timestamp(), reason or "", int(bool(retryable)),
                external_id or "",
                claim.key.report_id, claim.key.platform, claim.key.provider,
                self._profile_value(claim.key.profile), claim.key.recipient,
                claim.claim_id,
            ))
            return bool(cursor.rowcount)

    def _get_row(self, connection, key):
        return connection.execute("""
            SELECT report_id, platform, provider, profile, recipient, claim_id,
                   state, created_at, updated_at, reason, retryable, external_id
            FROM delivery_ledger
            WHERE report_id = ? AND platform = ? AND provider = ?
              AND profile = ? AND recipient = ?
        """, self._key_values(key)).fetchone()

    def _upsert_claim(self, connection, key, claim_id):
        now = self._timestamp()
        values = self._key_values(key)
        cursor = connection.execute("""
            UPDATE delivery_ledger
            SET claim_id = ?, state = 'claimed', updated_at = ?, reason = '',
                retryable = 0, external_id = ''
            WHERE report_id = ? AND platform = ? AND provider = ?
              AND profile = ? AND recipient = ?
        """, (claim_id, now) + values)
        if cursor.rowcount:
            return
        connection.execute("""
            INSERT INTO delivery_ledger (
                report_id, platform, provider, profile, recipient, claim_id,
                state, created_at, updated_at, reason, retryable, external_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'claimed', ?, ?, '', 0, '')
        """, values + (claim_id, now, now))

    def _key_values(self, key):
        return (
            key.report_id, key.platform, key.provider,
            self._profile_value(key.profile), key.recipient,
        )

    @staticmethod
    def _profile_value(profile):
        return "" if profile is None else profile

    def _timestamp(self):
        return self._now().replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    def _now(self):
        value = self._clock()
        if not isinstance(value, datetime):
            raise ValueError("ledger clock must return datetime")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
