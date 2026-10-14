#!/usr/bin/env python3
"""Validate an APIProof ledger and aggregate bounded evidence; Python 3.10+."""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit


class Invalid(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Invalid(message)


def obj(value, allowed, required, label):
    require(isinstance(value, dict), f'{label}: expected object')
    require(not set(value) - set(allowed), f'{label}: unknown fields {sorted(set(value) - set(allowed))}')
    require(set(required) <= set(value), f'{label}: missing {sorted(set(required) - set(value))}')


def string(value, label):
    require(isinstance(value, str) and bool(value.strip()), f'{label}: expected nonempty string')
    return value


def stamp(value):
    string(value, 'observed_at')
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise Invalid('observed_at: invalid ISO 8601 date') from exc
    require(d.tzinfo is not None and d.utcoffset() is not None, 'observed_at: timezone required')
    return d.astimezone(timezone.utc)


def source_url(value):
    string(value, 'source')
    try:
        u = urlsplit(value)
        port = u.port
    except ValueError as exc:
        raise Invalid('source: invalid URL') from exc
    require(u.scheme == 'https' and bool(u.hostname) and not u.username and not u.password
            and not u.query and not u.fragment and port in (None, 443)
            and not any(c.isspace() for c in value), 'source: use credential-free HTTPS URL without query/fragment')


def load_json(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'Duplicate JSON field: {key}')
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'),
                          object_pairs_hook=unique_object,
                          parse_constant=lambda v: (_ for _ in ()).throw(Invalid(f'Non-finite JSON number: {v}')))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Invalid(f'Cannot read valid JSON: {Path(path).name}') from exc


def validate_live(e, root):
    raw = string(e['artifact'], 'artifact')
    rel = Path(raw)
    require(not rel.is_absolute(), 'artifact must be relative')
    path = (root / rel).resolve()
    require(path.is_relative_to(root.resolve()), 'artifact must stay beneath ledger directory')
    require(path.is_file(), 'artifact file missing')
    require(isinstance(e['sha256'], str) and bool(re.fullmatch('[a-f0-9]{64}', e['sha256'])), 'invalid sha256')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == e['sha256'], 'artifact SHA-256 mismatch')
    a = load_json(path)
    require(isinstance(a, dict), 'artifact must be an object')
    require(type(a.get('schema_version')) is int and a['schema_version'] == 1, 'artifact schema version')
    for field in ('requirement_id', 'observed_at', 'outcome'):
        require(a.get(field) == e[field], f'artifact {field} mismatch')
    require(a.get('url') == e['source'], 'artifact URL mismatch')
    checks = a.get('checks')
    require(isinstance(checks, list) and bool(checks), 'artifact needs checks')
    for c in checks:
        require(isinstance(c, dict) and isinstance(c.get('name'), str) and bool(c['name'].strip())
                and type(c.get('passed')) is bool, 'artifact check invalid')
    passed = all(c['passed'] for c in checks)
    require(passed == (e['outcome'] == 'supports'), 'artifact outcome inconsistent with checks')


def validate(data, root):
    obj(data, ('schema_version', 'project', 'max_age_days', 'requirements', 'candidates'),
        ('schema_version', 'project', 'requirements', 'candidates'), 'ledger')
    require(type(data['schema_version']) is int and data['schema_version'] == 1, 'unsupported schema_version')
    string(data['project'], 'project')
    age = data.get('max_age_days', 30)
    require(type(age) is int and 1 <= age <= 365, 'max_age_days must be 1–365')
    rs = data['requirements']
    require(isinstance(rs, list) and bool(rs), 'requirements cannot be empty')
    ids = set()
    for r in rs:
        obj(r, ('id', 'text', 'required', 'proof'), ('id', 'text', 'required', 'proof'), 'requirement')
        string(r['id'], 'requirement.id'); string(r['text'], 'requirement.text')
        require(r['id'] not in ids, 'duplicate requirement ID'); ids.add(r['id'])
        require(type(r['required']) is bool, 'required must be boolean')
        require(r['proof'] in ('documentation', 'live'), 'proof must be documentation or live')
    require(any(r['required'] for r in rs), 'at least one must-have is required')
    cs = data['candidates']
    require(isinstance(cs, list) and bool(cs), 'candidates cannot be empty')
    seen = set()
    for c in cs:
        obj(c, ('id', 'name', 'evidence'), ('id', 'name', 'evidence'), 'candidate')
        string(c['id'], 'candidate.id'); string(c['name'], 'candidate.name')
        require(c['id'] not in seen, 'duplicate candidate ID'); seen.add(c['id'])
        require(isinstance(c['evidence'], list), 'evidence must be array')
        for e in c['evidence']:
            require(isinstance(e, dict), 'evidence must be object')
            kind = e.get('kind')
            require(kind in ('documentation', 'live'), 'invalid evidence kind')
            base = ('requirement_id', 'kind', 'outcome', 'source', 'observed_at')
            extra = ('excerpt',) if kind == 'documentation' else ('artifact', 'sha256')
            obj(e, base + extra + ('note', 'condition'), base + extra, 'evidence')
            string(e['requirement_id'], 'evidence.requirement_id')
            require(e['requirement_id'] in ids, 'unknown requirement ID')
            require(e['outcome'] in ('supports', 'refutes', 'unknown'), 'invalid evidence outcome')
            source_url(e['source']); stamp(e['observed_at'])
            for f in ('note', 'condition'):
                if f in e:
                    string(e[f], f)
            if kind == 'documentation':
                string(e['excerpt'], 'excerpt')
            else:
                validate_live(e, root)
    return data


def evaluate(data, root=Path('.'), now=None):
    validate(data, root)
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None, 'evaluation time needs timezone')
    cutoff = now - timedelta(days=data.get('max_age_days', 30))
    candidates = []
    for c in data['candidates']:
        rows = []
        for r in data['requirements']:
            evidences = [e for e in c['evidence'] if e['requirement_id'] == r['id']]
            usable, ignored = [], []
            for e in evidences:
                date = stamp(e['observed_at'])
                reason = ('future observation' if date > now else 'stale observation' if date < cutoff else
                          'live proof required' if r['proof'] == 'live' and e['kind'] != 'live'
                          and e['outcome'] != 'refutes' else None)
                if reason:
                    ignored.append({'source': e['source'], 'reason': reason})
                else:
                    usable.append(e)
            supports = [e for e in usable if e['outcome'] == 'supports']
            refutes = [e for e in usable if e['outcome'] == 'refutes']
            status = ('conflict' if supports and refutes else 'failed' if refutes else 'met' if supports else 'unknown')
            conditions = sorted({e['condition'] for e in usable if e.get('condition')})
            grade = 'live' if any(e['kind'] == 'live' for e in supports) else 'documentation' if supports else 'none'
            if status == 'met' and grade == 'documentation':
                conditions.append('Documented capability; runtime behavior was not verified.')
            rows.append({**r, 'status': status, 'evidence_grade': grade, 'conditions': conditions,
                         'evidence': evidences, 'ignored_evidence': ignored})
        must = [r for r in rows if r['required']]
        verdict = ('not fit' if any(r['status'] == 'failed' for r in must) else
                   'insufficient evidence' if any(r['status'] != 'met' for r in must) else
                   'fit with conditions' if any(r['status'] != 'met' or r['conditions'] for r in rows) else 'fit')
        candidates.append({'id': c['id'], 'name': c['name'], 'verdict': verdict, 'requirements': rows})
    return {'schema_version': 1, 'project': data['project'], 'evaluated_at': now.isoformat(),
            'max_age_days': data.get('max_age_days', 30), 'candidates': candidates,
            'limitations': ['Verdicts cover declared requirements and observation times only.',
                            'Source semantics are assessed by the agent; hashes bind recorded bytes, not source authenticity.',
                            'No claim of SLA, future uptime or hidden model identity.']}


def escape(value):
    value = str(value).replace('\n', ' ').replace('\r', ' ').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#!|])', r'\\\1', value)


def markdown(report):
    out = [f"# APIProof — {escape(report['project'])}", '', f"Evaluated: {report['evaluated_at']}", '']
    for c in report['candidates']:
        out += [f"## {escape(c['name'])}", '', f"Verdict: **{c['verdict']}**", '',
                '| Requirement | Priority | Status | Evidence | Conditions |', '| --- | --- | --- | --- | --- |']
        for r in c['requirements']:
            out.append('| ' + ' | '.join(escape(v) for v in (f"{r['id']}: {r['text']}",
                'must-have' if r['required'] else 'optional', r['status'], r['evidence_grade'], '; '.join(r['conditions']))) + ' |')
        for r in c['requirements']:
            out += ['', f"### {escape(r['id'])}: evidence"]
            if not r['evidence']:
                out.append('- No evidence recorded.')
            for e in r['evidence']:
                out.append(f"- {e['kind']} / {e['outcome']} / {e['observed_at']}: {escape(e['source'])}")
                out.append('  ' + escape(e.get('excerpt', f"Probe artifact: {e.get('artifact', '')}")))
                if e.get('note'):
                    out.append('  Note: ' + escape(e['note']))
            for i in r['ignored_evidence']:
                out.append(f"- Excluded: {escape(i['reason'])} — {escape(i['source'])}")
    out += ['', '## Limits', ''] + ['- ' + x for x in report['limitations']]
    return '\n'.join(out) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ledger', type=Path)
    p.add_argument('--output-dir', required=True, type=Path)
    a = p.parse_args()
    try:
        report = evaluate(load_json(a.ledger), a.ledger.resolve().parent)
        a.output_dir.mkdir(parents=True, exist_ok=True)
        (a.output_dir / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        (a.output_dir / 'report.md').write_text(markdown(report), encoding='utf-8')
    except (Invalid, OSError) as exc:
        print(f'APIProof: {exc}', file=sys.stderr)
        return 2
    for c in report['candidates']:
        print(f"{c['name']}: {c['verdict']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
