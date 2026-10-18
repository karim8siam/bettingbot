"""Exercise real HTTP retries without exchange access or credentials."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from client.rest_client import SXBetClient


def test_transient_read_retries_but_write_does_not():
    counts = {'GET': 0, 'POST': 0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            counts['GET'] += 1
            self.send_response(503 if counts['GET'] == 1 else 200)
            self.end_headers()
            self.wfile.write(b'{"status":"success","data":{"domain":{"name":"fixture"}}}')

        def do_POST(self):
            counts['POST'] += 1
            self.send_response(503)
            self.end_headers()

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = SXBetClient(f'http://127.0.0.1:{server.server_port}', timeout=2)
    client.session.mount('http://', client.session.get_adapter('https://'))
    try:
        assert client.get_metadata()['domain']['name'] == 'fixture'
        assert counts['GET'] == 2
        assert client.session.post(client.base_url, timeout=2).status_code == 503
        assert counts['POST'] == 1
    finally:
        client.session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
