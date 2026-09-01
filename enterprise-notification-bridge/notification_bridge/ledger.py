from __future__ import absolute_import

from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
import uuid


class DeliveryKey(namedtuple(
        "DeliveryKeyBase", "report_id platform provider profile recipient")):
    __slots__ = ()


class Claim(namedtuple("ClaimBase", "key claim_id acquired")):
    __slots__ = ()


class DeliveryLedger(object):
    """A local, metadata-only record of notification delivery attempts."""

    _STATES = (
        "claimed", "succeeded", "retryable_failure", "permanent_failure",
    )

    def __init__(self, path):
        self.path = path
        self._create_schema()

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
            if row and row["state"] in (
                    "claimed", "succeeded", "permanent_failure"):
                return Claim(key, row["claim_id"], False)

            claim_id = uuid.uuid4().hex
            self._upsert_claim(connection, key, claim_id)
            return Claim(key, claim_id, True)

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

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
