"""Entry point for hosts that run Python through Passenger (cPanel "Setup Python App")."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.server import application  # noqa: E402,F401
