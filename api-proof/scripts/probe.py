#!/usr/bin/env python3
"""Make one bounded HTTPS GET/HEAD probe; no response bodies or secrets in output."""
import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from evaluate import Invalid, load_json, obj, require, string

LIMIT = 1024 * 1024


def validate_spec(spec, hosts):
    obj(spec, ('requirement_id', 'url', 'method', 'headers_env', 'expect_status', 'json_equals', 'json_present', 'failure_outcome'),
        ('requirement_id', 'url', 'expect_status'), 'probe')
    string(spec['requirement_id'], 'requirement_id'); string(spec['url'], 'url')
    try:
        u = urlsplit(spec['url']); port = u.port
    except ValueError as exc:
        raise Invalid('invalid URL') from exc
    require(u.scheme == 'https' and u.hostname and not u.username and not u.password and not u.fragment
            and port in (None, 443) and not any(c.isspace() for c in spec['url']), 'HTTPS port 443, no credentials/fragments/whitespace required')
    require(u.hostname.lower() in {h.lower() for h in hosts}, 'host not explicitly allowed')
    for k, _ in parse_qsl(u.query):
        require(not re.search(r'key|token|secret|password|credential|signature|auth', k, re.I), 'put credentials in environment headers')
    require(spec.get('method', 'GET') in ('GET', 'HEAD'), 'only GET/HEAD supported')
    require(type(spec['expect_status']) is int and 100 <= spec['expect_status'] <= 599, 'invalid expect_status')
    require(spec.get('failure_outcome', 'unknown') in ('unknown', 'refutes'), 'invalid failure_outcome')
    headers = spec.get('headers_env', {})
    require(isinstance(headers, dict), 'headers_env must be object')
    for k, env in headers.items():
        require(bool(re.fullmatch(r'[A-Za-z0-9-]+', k)) and k.lower() not in ('host', 'content-length', 'transfer-encoding', 'connection'), 'invalid or reserved header')
        require(isinstance(env, str) and bool(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', env)), 'invalid environment name')
    eq, present = spec.get('json_equals', {}), spec.get('json_present', [])
    require(isinstance(eq, dict) and isinstance(present, list), 'invalid JSON assertions')
    for key in list(eq) + present:
        require(isinstance(key, str) and (key == '' or key.startswith('/')), 'assertions use JSON pointers')
    require(not (spec.get('method') == 'HEAD' and (eq or present)), 'HEAD cannot assert JSON body')
    return u


def public_addresses(host):
    try:
        entries = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise Invalid('DNS lookup failed') from exc
    addresses = list(dict.fromkeys(entry[4][0] for entry in entries))
    require(bool(addresses), 'DNS returned no address')
    require(all(ipaddress.ip_address(ip).is_global for ip in addresses), 'nonpublic destination denied')
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def pointer(data, path):
    for part in path.split('/')[1:] if path else []:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(data, list):
            require(bool(re.fullmatch(r'0|[1-9][0-9]*', part)), 'invalid array index')
            data = data[int(part)]
        else:
            data = data[part]
    return data


def run_probe(spec, hosts):
    u = validate_spec(spec, hosts)
    addresses = public_addresses(u.hostname)
    headers = {'Accept': 'application/json', 'User-Agent': 'APIProof/0.1'}
    for name, env in spec.get('headers_env', {}).items():
        val = os.environ.get(env)
        require(val is not None and bool(val) and '\r' not in val and '\n' not in val, f'missing or invalid environment header: {env}')
        headers[name] = val
    safe_url = urlunsplit(('https', u.netloc, u.path or '/', '', ''))
    checks = []
    record = {'schema_version': 1, 'requirement_id': spec['requirement_id'], 'url': safe_url,
              'observed_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
              'request_target_sha256': hashlib.sha256((u.path + '?' + u.query).encode()).hexdigest()}
    conn = PinnedHTTPS(u.hostname, addresses[0])
    try:
        target = (u.path or '/') + ('?' + u.query if u.query else '')
        conn.request(spec.get('method', 'GET'), target, headers=headers)
        response = conn.getresponse()
        body = response.read(LIMIT + 1)
        require(len(body) <= LIMIT, 'response exceeds 1 MiB')
        record.update({'status_code': response.status, 'response_bytes': len(body),
                       'response_sha256': hashlib.sha256(body).hexdigest()})
        checks.append({'name': f"HTTP status equals {spec['expect_status']}", 'passed': response.status == spec['expect_status']})
        if spec.get('json_equals') or spec.get('json_present'):
            try:
                data = json.loads(body)
                valid = True
            except (ValueError, UnicodeError):
                data, valid = None, False
            checks.append({'name': 'response is JSON', 'passed': valid})
            for key in spec.get('json_present', []):
                try:
                    pointer(data, key); passed = valid
                except (KeyError, IndexError, TypeError, Invalid):
                    passed = False
                checks.append({'name': 'JSON pointer exists: ' + key, 'passed': passed})
            for key, expected in spec.get('json_equals', {}).items():
                try:
                    actual = pointer(data, key)
                    passed = valid and type(actual) is type(expected) and actual == expected
                except (KeyError, IndexError, TypeError, Invalid):
                    passed = False
                checks.append({'name': 'JSON pointer equals expected value: ' + key, 'passed': passed})
        good = all(c['passed'] for c in checks)
        access_failure = response.status in (401, 403, 408, 429) or response.status >= 500 or 300 <= response.status < 400
        record['outcome'] = 'supports' if good else 'unknown' if access_failure else spec.get('failure_outcome', 'unknown')
    except (OSError, http.client.HTTPException, Invalid, ValueError):
        checks.append({'name': 'bounded HTTPS request completed', 'passed': False})
        record['outcome'] = 'unknown'
        record['error'] = 'Request failed, timed out, or exceeded response limit; endpoint suitability is unproven.'
    finally:
        conn.close()
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('spec', type=Path)
    p.add_argument('--allow-host', required=True, action='append')
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    try:
        result = run_probe(load_json(a.spec), a.allow_host)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(result['outcome'])
        return 0 if result['outcome'] == 'supports' else 1
    except (Invalid, OSError) as exc:
        print(f'APIProof probe: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
