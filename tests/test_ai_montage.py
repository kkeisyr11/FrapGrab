import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from core.ai_montage import prepare_brief, validate_plan
from core.chatgpt_plan import AUTH, PLAN_SCOPE, ChatGPTPlan, _identity, _read_reply
from core.editor import plan_montage


VIDEO = {"format": {"duration": "14.0"}, "streams": [{"codec_type": "video"}]}


class AIMontageTests(unittest.TestCase):
    def test_brief_omits_paths_and_the_validated_order_drives_the_editor(self):
        paths = [Path("Private-name.mp4"), Path("Other.mp4")]
        with patch("core.ai_montage.probe", return_value=VIDEO), patch("core.ai_montage._metadata_events", return_value=[
                {"time": 2.5, "type": "kill", "note": "Private chat"}]):
            brief, key, sources = prepare_brief(paths, "Open with an elimination", 30, True, "en")
        self.assertNotIn("Private", brief)
        self.assertIn('"time": 2.5', brief)
        title, cuts = validate_plan(json.dumps({"request_id": key, "title": "Best plays", "cuts": [
            {"clip": "C02", "start": 2, "end": 7},
            {"clip": "C01", "start": 1, "end": 4},
        ]}), key, sources)
        with patch("core.editor.probe", return_value=VIDEO):
            plan = plan_montage(paths, selection_mode="ai", ai_cuts=cuts)
        self.assertEqual(title, "Best plays")
        self.assertEqual([(item[0], item[2], item[3]) for item in plan["jobs"]],
                         [(paths[1], 2, 5), (paths[0], 1, 3)])
        self.assertEqual(plan["estimated_duration"], 8)

    def test_foreign_out_of_bounds_and_duplicate_cuts_are_rejected(self):
        sources = {"C01": (Path("clip.mp4"), 14.0)}
        cut = {"clip": "C01", "start": 1, "end": 4}
        for key, rows in [("old", [cut]), ("new", [dict(cut, clip="other")]),
                          ("new", [dict(cut, end=15)]), ("new", [cut, cut])]:
            with self.subTest(key=key, rows=rows), self.assertRaises(ValueError):
                validate_plan(json.dumps({"request_id": key, "title": "", "cuts": rows}), "new", sources)


class ChatGPTPlanTests(unittest.TestCase):
    def test_loopback_registration_validates_nonce_and_keeps_tokens_off_disk(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        issued = "oaiapp_test"
        query = {}
        def browser(url):
            query.update({k: v[0] for k, v in parse_qs(urlsplit(url).query).items()})
            def callback():
                args = urlencode({"state": query["state"], "code": "one-time-code", "client_id": issued})
                with urlopen(query["redirect_uri"] + "?" + args, timeout=5):
                    pass
            threading.Thread(target=callback, daemon=True).start()
            return True

        def token(form):
            self.assertEqual(form["client_id"], issued)
            self.assertEqual(form["redirect_uri"], query["redirect_uri"])
            claim = {"sub": "test-user", "iss": AUTH, "aud": issued, "exp": time.time() + 60, "nonce": query["nonce"]}
            encoded = jwt.encode(claim, private, algorithm="RS256")
            return {"id_token": encoded, "access_token": "test-secret", "expires_in": 300, "scope": PLAN_SCOPE}

        with tempfile.TemporaryDirectory() as folder, patch("core.chatgpt_plan.CONFIG_DIR", folder), \
                patch("core.chatgpt_plan.webbrowser.open", side_effect=browser), \
                patch("core.chatgpt_plan._token", side_effect=token), patch("jwt.PyJWKClient") as jwks:
            jwks.return_value.get_signing_key_from_jwt.return_value.key = private.public_key()
            client = ChatGPTPlan()
            client.connect(lambda: False)
            self.assertEqual(client.tokens["access_token"], "test-secret")
            self.assertNotIn("test-secret", client.registration.read_text(encoding="utf-8"))
            with self.assertRaises(RuntimeError):
                _identity(client.tokens["id_token"], issued, "wrong-nonce")

    def test_inference_requires_stream_completion(self):
        delta = b'data: {"type":"response.output_text.delta","delta":"{}"}\n'
        completed = b'data: {"type":"response.completed"}\n'
        self.assertEqual(_read_reply(io.BytesIO(delta + completed), lambda: False), "{}")
        with self.assertRaises(RuntimeError):
            _read_reply(io.BytesIO(delta), lambda: False)

    def test_inference_uses_eligible_model_and_plan_token(self):
        from core.chatgpt_plan import API
        client = ChatGPTPlan()
        client._set_tokens({"access_token": "oauth-test", "scope": PLAN_SCOPE, "expires_in": 300}, "oaiapp_test")
        models = io.BytesIO(b'{"models":[{"visibility":"list","slug":"test-model"}]}')
        reply = io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"{}"}\n'
                           b'data: {"type":"response.completed"}\n')
        with patch("core.chatgpt_plan._request", side_effect=[models, reply]) as call:
            self.assertEqual(client.propose("test brief", lambda: False), "{}")
        url, = call.call_args.args
        self.assertEqual(url, API + "/responses")
        self.assertEqual(call.call_args.kwargs["headers"]["Authorization"], "Bearer oauth-test")
        self.assertEqual(json.loads(call.call_args.kwargs["data"]), {
            "model": "test-model", "input": [{"role": "user", "content": "test brief"}],
            "store": False, "stream": True,
        })
