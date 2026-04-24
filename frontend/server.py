from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

PORT = 5173
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', PORT), SimpleHTTPRequestHandler)
    print(f'Frontend server running at http://localhost:{PORT}')
    server.serve_forever()
