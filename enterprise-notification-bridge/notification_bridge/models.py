from __future__ import absolute_import

from collections import OrderedDict


class Envelope(object):
    schema_version = "1"

    def __init__(self, report_id, generated_at, detector, report, ai_summary):
        self.report_id = report_id
        self.generated_at = generated_at
        self.detector = detector
        self.report = report
        self.ai_summary = ai_summary

    def to_dict(self):
        return OrderedDict([
            ("schema_version", self.schema_version),
            ("report_id", self.report_id),
            ("generated_at", self.generated_at),
            ("detector", self.detector),
            ("report", self.report),
            ("ai_summary", self.ai_summary),
        ])
