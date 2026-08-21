#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer run.sh or run.ps1."""

from __future__ import absolute_import

import sys

from wifi_health.cli import main


if __name__ == "__main__":
    sys.exit(main())
