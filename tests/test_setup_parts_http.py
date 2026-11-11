"""The Windows Python builder's downloads (builder/py/hookshot_builder/setup_parts.py, updater.py) keep to the rules the
Linux updater has (builder/linux/linux_update.py): every redirect hop must stay on https (urllib's own handler follows
one to http:, and only the last link was looked at), a download stops as soon as it is longer than the list says (or
than a list or an API answer can be) instead of being read whole first, and the tag the builder reads for the latest
release is one the setup list's rules accept.

python -I -B tests/test_setup_parts_http.py
"""
import http.server
import io
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "builder" / "py"))
from hookshot_builder import setup_parts, updater  # noqa: E402


class Body(io.BytesIO):
    """a response of n bytes that counts how much was read of it"""

    def __init__(self, data, url="https://github.com/x"):
        super().__init__(data)
        self.status, self.url, self.taken = 200, url, 0

    def geturl(self):
        return self.url

    def read(self, n=-1):
        b = super().read(n)
        self.taken += len(b)
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Opener:
    def __init__(self, body):
        self.body, self.asked = body, []

    def open(self, req, timeout=None):
        self.asked.append(req.full_url)
        return self.body


class Redirects(http.server.BaseHTTPRequestHandler):
    def do_GET(self):   # noqa: N802
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:%d/next" % self.server.server_port)
        self.end_headers()

    def log_message(self, *a):
        pass


class HttpTests(unittest.TestCase):
    def test_a_redirect_to_http_is_refused_at_that_hop(self):
        handler = setup_parts._HttpsRedirects()
        req = urllib.request.Request("https://github.com/a")
        with self.assertRaises(setup_parts.RedirectRefused):
            handler.redirect_request(req, None, 302, "Found", {}, "http://evil.invalid/b")
        nxt = handler.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/b")
        self.assertEqual(nxt.full_url, "https://objects.githubusercontent.com/b")
        # (the real opener, against a server that redirects to http:)
        server = http.server.HTTPServer(("127.0.0.1", 0), Redirects)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(setup_parts.RedirectRefused):
                setup_parts.OPENER.open("http://127.0.0.1:%d/first" % server.server_port, timeout=5)
        finally:
            server.shutdown()
            server.server_close()

    def test_a_refused_redirect_is_not_tried_again(self):
        calls = []

        def get(self, url, *a, **kw):
            calls.append(url)
            raise setup_parts.RedirectRefused("A download was redirected away from https")
        with mock.patch.object(setup_parts.Http, "get", get), mock.patch.object(setup_parts.time, "sleep", lambda s: None):
            with self.assertRaises(setup_parts.RedirectRefused):
                setup_parts.read_manifest(lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_a_download_longer_than_listed_stops_early(self):
        body = Body(b"x" * (10 << 20))
        got = []
        with mock.patch.object(setup_parts, "OPENER", Opener(body)):
            with self.assertRaises(setup_parts.SetupError):
                setup_parts.Http().get("https://github.com/p.zip", got.append, expect=1 << 20)
        self.assertLessEqual(sum(map(len, got)), 1 << 20)   # (nothing past the size reached the file)
        self.assertLess(body.taken, 2 << 20)                # (and the rest was not read)
        # (the size it says: taken whole)
        with mock.patch.object(setup_parts, "OPENER", Opener(Body(b"y" * 1000))):
            out = []
            setup_parts.Http().get("https://github.com/p.zip", out.append, expect=1000)
            self.assertEqual(sum(map(len, out)), 1000)

    def test_a_list_has_a_ceiling(self):
        body = Body(b"tag v1\n" + b"#" * (64 << 20))
        with mock.patch.object(setup_parts, "OPENER", Opener(body)), self.assertRaises(setup_parts.SetupError):
            setup_parts.Http().get("https://github.com/hookshot-setup.txt")
        self.assertLess(body.taken, setup_parts.MAX_BODY + (1 << 20))
        with mock.patch.object(setup_parts, "OPENER", Opener(Body(b"tag v1\n"))):
            self.assertEqual(setup_parts.Http().get("https://github.com/hookshot-setup.txt"), b"tag v1\n")

    def test_the_latest_tag_is_a_name_the_list_rules_accept(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env, mock.patch.object(updater.time, "sleep", lambda s: None):
            env.pop("HOOKSHOT_LATEST_TAG", None)
            for answer, want in (({"tag_name": "v2.1.0"}, "v2.1.0"), ({"tag_name": "../../x"}, None),
                                 ({"tag_name": "v2 --fetched"}, None), ({"tag_name": 7}, None)):
                with self.subTest(answer=answer), mock.patch.object(setup_parts, "OPENER", Opener(Body(json.dumps(answer).encode()))):
                    self.assertEqual(updater.latest_tag(), want)
            with mock.patch.object(setup_parts, "OPENER", Opener(Body(b"{" + b" " * (32 << 20)))):
                self.assertIsNone(updater.latest_tag())


if __name__ == "__main__":
    unittest.main()
