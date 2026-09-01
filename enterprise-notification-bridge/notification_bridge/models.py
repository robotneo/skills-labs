from __future__ import absolute_import

import copy
from collections import OrderedDict


class Envelope(object):
    """Immutable-by-interface delivery envelope with defensive payload copies."""

    __slots__ = (
        "_schema_version", "_report_id", "_generated_at", "_detector",
        "_report", "_ai_summary",
    )

    def __init__(self, report_id, generated_at, detector, report, ai_summary,
                 schema_version="1"):
        self._schema_version = schema_version
        self._report_id = report_id
        self._generated_at = generated_at
        self._detector = copy.deepcopy(detector)
        self._report = copy.deepcopy(report)
        self._ai_summary = copy.deepcopy(ai_summary)

    @property
    def schema_version(self):
        return self._schema_version

    @property
    def report_id(self):
        return self._report_id

    @property
    def generated_at(self):
        return self._generated_at

    @property
    def detector(self):
        return copy.deepcopy(self._detector)

    @property
    def report(self):
        return copy.deepcopy(self._report)

    @property
    def ai_summary(self):
        return copy.deepcopy(self._ai_summary)

    def to_dict(self):
        return OrderedDict([
            ("schema_version", self._schema_version),
            ("report_id", self._report_id),
            ("generated_at", self._generated_at),
            ("detector", copy.deepcopy(self._detector)),
            ("report", copy.deepcopy(self._report)),
            ("ai_summary", copy.deepcopy(self._ai_summary)),
        ])

    def with_ai_summary(self, mode, text):
        return Envelope(
            self._report_id, self._generated_at, self._detector, self._report,
            {"mode": mode, "text": text}, self._schema_version,
        )
