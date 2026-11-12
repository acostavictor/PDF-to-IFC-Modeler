"""Run the app locally: python tools/dev_server.py [port]. Then open http://localhost:8000/"""
import os
import sys
from wsgiref.simple_server import make_server

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.server import application  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("PDF to IFC Modeler on http://localhost:%d/" % port)
    make_server("127.0.0.1", port, application).serve_forever()
