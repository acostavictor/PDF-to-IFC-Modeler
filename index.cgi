#!/usr/bin/env python3
"""CGI entry point for shared hosting (for example HostGator cPanel). Needs Python 3.6+ and nothing else."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wsgiref.handlers import CGIHandler      # noqa: E402
from app.server import application           # noqa: E402

if __name__ == "__main__":
    CGIHandler().run(application)
