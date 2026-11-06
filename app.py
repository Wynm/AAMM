#!/usr/bin/env python3
"""AAMM: a small, local-first opportunity tracker (Python standard library only)."""
import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('AAMM_DB', ROOT / 'data' / 'aamm.sqlite3'))
STATUSES = ('new', 'contacted', 'qualified', 'proposal', 'won', 'lost')
FIELDS = ('name', 'company', 'service', 'value', 'probability', 'status', 'next_action', 'due_date', 'notes')

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT NOT NULL DEFAULT '',
            service TEXT NOT NULL DEFAULT '', value REAL NOT NULL DEFAULT 0,
            probability INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new',
            next_action TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

def validate(data):
    if not isinstance(data, dict): raise ValueError('البيانات غير صالحة')
    result = {}
    for field in ('name', 'company', 'service', 'next_action', 'due_date', 'notes'):
        value = data.get(field, '')
        if not isinstance(value, str): raise ValueError('الحقول النصية يجب أن تكون نصًا')
        result[field] = value.strip()
        if len(result[field]) > (4000 if field == 'notes' else 250): raise ValueError('النص طويل جدًا')
    if not result['name']: raise ValueError('اسم العميل مطلوب')
    try:
        result['value'] = float(data.get('value', 0))
        probability = float(data.get('probability', 0))
        if not 0 <= result['value'] <= 1000000000 or not 0 <= probability <= 100 or not probability.is_integer(): raise ValueError()
        result['probability'] = int(probability)
    except (TypeError, ValueError, OverflowError): raise ValueError('تحقق من قيمة الصفقة والاحتمال (من 0 إلى 100)')
    result['status'] = data.get('status', 'new')
    if result['status'] not in STATUSES: raise ValueError('المرحلة غير صالحة')
    if result['due_date']:
        try:
            parsed = date.fromisoformat(result['due_date'])
            if parsed.isoformat() != result['due_date'] or parsed == date.max: raise ValueError()
        except ValueError: raise ValueError('التاريخ غير صالح')
    return result

def rows():
    with connect() as con: return [dict(row) for row in con.execute('SELECT * FROM opportunities ORDER BY id DESC')]

def save(data, ident=None):
    item = validate(data)
    with connect() as con:
        if ident is None:
            cur = con.execute('INSERT INTO opportunities (' + ','.join(FIELDS) + ') VALUES (' + ','.join('?' for _ in FIELDS) + ')', [item[f] for f in FIELDS])
            return cur.lastrowid
        cur = con.execute('UPDATE opportunities SET ' + ','.join(f + '=?' for f in FIELDS) + ',updated_at=CURRENT_TIMESTAMP WHERE id=?', [item[f] for f in FIELDS] + [ident])
        if not cur.rowcount: raise LookupError('الفرصة غير موجودة')
        return ident

def delete(ident):
    with connect() as con:
        if not con.execute('DELETE FROM opportunities WHERE id=?', (ident,)).rowcount: raise LookupError('الفرصة غير موجودة')

def csv_export(items):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=('id',) + FIELDS, extrasaction='ignore')
    writer.writeheader()
    for item in items:
        # Spreadsheet formula injection protection, including whitespace-prefixed formulas.
        writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else v for k, v in item.items()})
    return '\ufeff' + output.getvalue()

def ical_escape(value):
    """Escape untrusted text for RFC 5545 content lines."""
    return value.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n')

def ical_fold(line):
    # Fold at 75 octets without splitting a UTF-8 character; continuation space counts.
    parts, current, size = [], '', 0
    for char in line:
        length = len(char.encode('utf-8'))
        if size + length > 75:
            parts.append(current)
            current, size = ' ', 1
        current += char
        size += length
    parts.append(current)
    return '\r\n'.join(parts)

def calendar_export(items, now=None):
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//AAMM//Follow-ups//AR', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    for item in items:
        if item['status'] in ('won', 'lost') or not item['due_date']:
            continue
        try:
            due = date.fromisoformat(item['due_date'])
            end = due + timedelta(days=1)
        except (ValueError, OverflowError):
            continue  # Ignore malformed dates in databases created by older versions.
        summary = item['next_action'] or 'متابعة العميل'
        description = 'العميل: ' + item['name']
        if item['company']: description += '\nالشركة: ' + item['company']
        lines.extend(['BEGIN:VEVENT', f"UID:opportunity-{item['id']}@aamm.local", 'DTSTAMP:' + stamp,
                      'DTSTART;VALUE=DATE:' + due.strftime('%Y%m%d'), 'DTEND;VALUE=DATE:' + end.strftime('%Y%m%d'),
                      'SUMMARY:' + ical_escape(summary), 'DESCRIPTION:' + ical_escape(description), 'END:VEVENT'])
    lines.append('END:VCALENDAR')
    return '\r\n'.join(ical_fold(line) for line in lines) + '\r\n'

class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        password = os.environ.get('AAMM_PASSWORD')
        if not password: return True
        import base64
        expected = 'Basic ' + base64.b64encode(('aamm:' + password).encode()).decode()
        return secrets.compare_digest(self.headers.get('Authorization', ''), expected)
    def send(self, status, body, content_type='application/json; charset=utf-8', extra=None):
        if isinstance(body, str): body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'")
        for key, value in (extra or {}).items(): self.send_header(key, value)
        self.end_headers(); self.wfile.write(body)
    def check(self):
        if self.authorized(): return True
        self.send(401, 'Authentication required', 'text/plain', {'WWW-Authenticate': 'Basic realm="AAMM"'})
        return False
    def do_GET(self):
        if not self.check(): return
        path = urlparse(self.path).path
        if path == '/api/opportunities': return self.send(200, json.dumps(rows(), ensure_ascii=False))
        if path == '/api/export': return self.send(200, csv_export(rows()), 'text/csv; charset=utf-8', {'Content-Disposition': 'attachment; filename="opportunities.csv"'})
        if path == '/api/calendar': return self.send(200, calendar_export(rows()), 'text/calendar; charset=utf-8', {'Content-Disposition': 'attachment; filename="follow-ups.ics"'})
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path not in files: return self.send(404, 'Not found', 'text/plain')
        filename, mime = files[path]
        self.send(200, (ROOT / 'static' / filename).read_bytes(), mime)
    def change(self):
        if not self.check(): return
        # Browsers always send Origin on cross-origin JSON requests; reject mismatches.
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.send(403, json.dumps({'error': 'Origin not allowed'}))
        path = urlparse(self.path).path.strip('/').split('/')
        if len(path) not in (2, 3) or path[:2] != ['api', 'opportunities']:
            return self.send(404, '{}')
        try:
            ident = int(path[2]) if len(path) == 3 else None
            if self.command == 'DELETE':
                if ident is None: raise ValueError('معرّف الفرصة مطلوب')
                delete(ident); return self.send(200, '{}')
            if self.command == 'PUT' and ident is None: raise ValueError('معرّف الفرصة مطلوب')
            if self.command == 'POST' and ident is not None: raise ValueError('مسار غير صالح')
            if self.headers.get_content_type() != 'application/json': raise ValueError('Expected JSON')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384: raise ValueError('حجم الطلب غير صالح')
            data = json.loads(self.rfile.read(length))
            saved = save(data, ident)
            self.send(200 if ident else 201, json.dumps({'id': saved}))
        except LookupError as exc: self.send(404, json.dumps({'error': str(exc)}, ensure_ascii=False))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc: self.send(400, json.dumps({'error': str(exc)}, ensure_ascii=False))
    do_POST = change
    do_PUT = change
    do_DELETE = change

if __name__ == '__main__':
    init_db()
    host = os.environ.get('AAMM_HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))
    print(f'AAMM running on http://{host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
