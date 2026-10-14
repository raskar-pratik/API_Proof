import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from evaluate import Invalid, evaluate, markdown, load_json
from probe import validate_spec, public_addresses, pointer, run_probe

NOW = datetime(2026, 10, 14, 9, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def ledger():
    return {'schema_version': 1, 'project': 'Weather dashboard', 'requirements': [
        {'id': 'R1', 'text': 'Temperature', 'required': True, 'proof': 'documentation'}],
        'candidates': [{'id': 'a', 'name': 'A', 'evidence': []}]}


def doc(outcome='supports'):
    return {'requirement_id': 'R1', 'kind': 'documentation', 'outcome': outcome,
            'source': 'https://provider.example/docs', 'excerpt': 'Relevant claim.', 'observed_at': STAMP}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.d = ledger()

    def tearDown(self):
        self.temp.cleanup()

    def outcome(self):
        return evaluate(self.d, self.root, NOW)['candidates'][0]

    def live(self):
        a = {'schema_version': 1, 'requirement_id': 'R1', 'url': 'https://provider.example/api',
             'observed_at': STAMP, 'outcome': 'supports', 'checks': [{'name': 'JSON field', 'passed': True}]}
        raw = json.dumps(a).encode()
        (self.root / 'probe.json').write_bytes(raw)
        e = {'requirement_id': 'R1', 'kind': 'live', 'outcome': 'supports', 'source': a['url'],
             'observed_at': STAMP, 'artifact': 'probe.json', 'sha256': hashlib.sha256(raw).hexdigest()}
        self.d['candidates'][0]['evidence'] = [e]
        return e

    def test_missing(self):
        self.assertEqual(self.outcome()['verdict'], 'insufficient evidence')

    def test_documented(self):
        self.d['candidates'][0]['evidence'] = [doc()]
        self.assertEqual(self.outcome()['verdict'], 'fit with conditions')

    def test_refuted(self):
        self.d['candidates'][0]['evidence'] = [doc('refutes')]
        self.assertEqual(self.outcome()['verdict'], 'not fit')

    def test_verified(self):
        self.live()
        self.assertEqual(self.outcome()['verdict'], 'fit')

    def test_live_required(self):
        self.d['requirements'][0]['proof'] = 'live'
        self.d['candidates'][0]['evidence'] = [doc()]
        self.assertEqual(self.outcome()['verdict'], 'insufficient evidence')

    def test_conflict(self):
        self.live()
        self.d['requirements'][0]['proof'] = 'live'
        self.d['candidates'][0]['evidence'].append(doc('refutes'))
        self.assertEqual(self.outcome()['verdict'], 'insufficient evidence')
        self.assertEqual(self.outcome()['requirements'][0]['status'], 'conflict')

    def test_optional(self):
        self.live()
        self.d['requirements'].append({'id': 'R2', 'text': 'History', 'required': False, 'proof': 'live'})
        self.assertEqual(self.outcome()['verdict'], 'fit with conditions')

    def test_condition(self):
        self.live()['condition'] = 'Sandbox only'
        self.assertEqual(self.outcome()['verdict'], 'fit with conditions')

    def test_freshness(self):
        for days in (-1, 31):
            e = doc(); e['observed_at'] = (NOW - timedelta(days=days)).isoformat()
            self.d['candidates'][0]['evidence'] = [e]
            self.assertEqual(self.outcome()['verdict'], 'insufficient evidence')

    def test_invalid_dates(self):
        for value in ('2026-10-14', 'invalid'):
            e = doc(); e['observed_at'] = value
            self.d['candidates'][0]['evidence'] = [e]
            with self.assertRaises(Invalid): self.outcome()

    def test_tampering(self):
        self.live()
        (self.root / 'probe.json').write_text('{}')
        with self.assertRaisesRegex(Invalid, 'SHA-256'): self.outcome()

    def test_path_escape(self):
        for path in ('../probe.json', '/tmp/probe.json'):
            self.live()['artifact'] = path
            with self.assertRaises(Invalid): self.outcome()

    def test_mismatched_artifact(self):
        self.live()['observed_at'] = (NOW - timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(Invalid, 'mismatch'): self.outcome()

    def test_invalid_structure(self):
        bad = []
        d = ledger(); d['requirements'] = []; bad.append(d)
        d = ledger(); d['requirements'][0]['required'] = 'true'; bad.append(d)
        d = ledger(); d['requirements'].append(copy.deepcopy(d['requirements'][0])); bad.append(d)
        d = ledger(); d['max_age_days'] = True; bad.append(d)
        d = ledger(); d['surprise'] = 1; bad.append(d)
        d = ledger(); d['requirements'][0]['required'] = False; bad.append(d)
        for d in bad:
            with self.assertRaises(Invalid): evaluate(d, self.root, NOW)

    def test_nonfinite_json(self):
        p = self.root / 'bad.json'; p.write_text('{"x":NaN}')
        with self.assertRaises(Invalid): load_json(p)

    def test_duplicate_json_fields(self):
        p = self.root / 'bad.json'; p.write_text('{"project":"A","project":"B"}')
        with self.assertRaises(Invalid): load_json(p)

    def test_unhashable_reference(self):
        e = doc(); e['requirement_id'] = []
        self.d['candidates'][0]['evidence'] = [e]
        with self.assertRaises(Invalid): self.outcome()

    def test_symlink_escape(self):
        self.live()
        (self.root / 'outside.json').symlink_to('/etc/passwd')
        self.d['candidates'][0]['evidence'][0]['artifact'] = 'outside.json'
        with self.assertRaises(Invalid): self.outcome()

    def test_markdown_escaping(self):
        self.d['requirements'][0]['text'] = 'a|b\n<script>'
        result = markdown(evaluate(self.d, self.root, NOW))
        self.assertIn('a\\|b &lt;script&gt;', result)
        self.assertIn('No evidence recorded', result)

    def test_markdown_link_injection(self):
        self.d['project'] = '![x](https://evil.example)'
        result = markdown(evaluate(self.d, self.root, NOW))
        self.assertNotIn('![x](', result)


class ProbeTests(unittest.TestCase):
    def spec(self):
        return {'requirement_id': 'R1', 'url': 'https://api.example/weather', 'expect_status': 200,
                'json_present': ['/temperature'], 'json_equals': {'/units': 'celsius'}}

    def test_host_and_method_guards(self):
        for changes in ({'url': 'http://api.example/'}, {'method': 'POST'},
                        {'url': 'https://api.example/?api_key=secret'}, {'method': 'HEAD'},
                        {'url': 'https://user:secret@api.example/'}, {'url': 'https://api.example:8443/'}):
            s = self.spec(); s.update(changes)
            with self.assertRaises(Invalid): validate_spec(s, ['api.example'])
        with self.assertRaises(Invalid): validate_spec(self.spec(), ['other.example'])

    def test_private_dns(self):
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(Invalid): public_addresses('api.example')

    def test_pointer(self):
        self.assertEqual(pointer({'a/b': [{'~': 5}]}, '/a~1b/0/~0'), 5)
        with self.assertRaises(Invalid): pointer([1], '/-1')

    def mocked_probe(self, status=200, body=b'{"temperature":21,"units":"celsius"}', changes=None):
        class Response:
            def read(self, limit): return body
        Response.status = status
        response = Response()
        class Connection:
            def __init__(self, *a): pass
            def request(self, *a, **kw): pass
            def getresponse(self): return response
            def close(self): pass
        s = self.spec(); s.update(changes or {})
        with patch('probe.public_addresses', return_value=['1.1.1.1']), patch('probe.PinnedHTTPS', Connection):
            return run_probe(s, ['api.example'])

    def test_observation(self):
        result = self.mocked_probe()
        self.assertEqual(result['outcome'], 'supports')
        self.assertNotIn('temperature', json.dumps(result['response_sha256']))
        self.assertNotIn('body', result)

    def test_failure_is_unknown(self):
        for status in (401, 403, 429, 500, 302):
            self.assertEqual(self.mocked_probe(status=status, changes={'failure_outcome': 'refutes'})['outcome'], 'unknown')

    def test_json_mismatch(self):
        self.assertEqual(self.mocked_probe(body=b'{"units":"fahrenheit"}', changes={'failure_outcome': 'refutes'})['outcome'], 'refutes')
        self.assertEqual(self.mocked_probe(body=b'not json')['outcome'], 'unknown')

    def test_size_limit(self):
        self.assertEqual(self.mocked_probe(body=b'x' * (1024 * 1024 + 1))['outcome'], 'unknown')

    def test_secret_header_is_not_recorded(self):
        with patch.dict(os.environ, {'DEMO_AUTH': 'Bearer secret-value'}):
            result = self.mocked_probe(changes={'headers_env': {'Authorization': 'DEMO_AUTH'}})
        self.assertNotIn('secret-value', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
