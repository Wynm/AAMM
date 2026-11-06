import csv
import io
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.tmp.name) / 'test.sqlite3'
        app.init_db()
    def tearDown(self):
        app.DB = self.old_db
        self.tmp.cleanup()
    def test_lifecycle(self):
        ident = app.save({'name': 'سلمى', 'value': '2000', 'probability': '25'})
        self.assertEqual(app.rows()[0]['value'], 2000)
        app.save({'name': 'سلمى', 'status': 'won'}, ident)
        self.assertEqual(app.rows()[0]['status'], 'won')
        app.delete(ident)
        self.assertEqual(app.rows(), [])
        with self.assertRaises(LookupError): app.delete(ident)
    def test_validation(self):
        for data in ({'name':''}, {'name':'a','value':'nan'}, {'name':'a','probability':101}, {'name':'a','probability':1.5}, {'name':'a','status':'other'}, {'name':'a','due_date':'2025-02-30'}):
            with self.subTest(data=data), self.assertRaises(ValueError): app.save(data)
    def test_csv_formula_safety(self):
        app.save({'name': '=1+1', 'company': '  @evil'})
        result = list(csv.DictReader(io.StringIO(app.csv_export(app.rows()).lstrip('\ufeff'))))[0]
        self.assertEqual(result['name'], "'=1+1")
        self.assertEqual(result['company'], "'@evil")
    def test_update_missing(self):
        with self.assertRaises(LookupError): app.save({'name':'a'}, 42)


class CalendarTests(unittest.TestCase):
    def test_calendar_dates_escaping_and_folding(self):
        from datetime import datetime, timezone
        items = [dict(id=1, status='new', due_date='2026-02-28', next_action='متابعة، عميل\nBEGIN:VEVENT' + 'س'*70, name='عميل;أ', company='مثال'),
                 dict(id=2, status='won', due_date='2026-02-28', next_action='', name='x', company=''),
                 dict(id=3, status='new', due_date='', next_action='', name='x', company='')]
        result = app.calendar_export(items, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(result.count('BEGIN:VEVENT'), 2)  # the second is escaped text, not a line
        self.assertEqual(sum(line == 'BEGIN:VEVENT' for line in result.split('\r\n')), 1)
        self.assertIn('DTEND;VALUE=DATE:20260301', result)
        self.assertIn('\\nBEGIN:VEVENT', result)
        self.assertIn('عميل\\;أ', result.replace('\r\n ', ''))
        self.assertTrue(all(len(line.encode('utf-8')) <= 75 for line in result.split('\r\n')))
    def test_date_must_be_canonical_and_have_next_day(self):
        for value in ('20260101', '9999-12-31'):
            with self.subTest(value=value), self.assertRaises(ValueError): app.validate({'name':'a', 'due_date':value})

class BackupTests(unittest.TestCase):
    def test_online_backup_and_no_overwrite(self):
        import backup
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            old = app.DB
            app.DB = Path(directory) / 'source.sqlite3'
            try:
                app.init_db()
                app.save({'name':'عميل'})
                destination = Path(directory) / 'backup.sqlite3'
                backup.backup(app.DB, destination)
                with sqlite3.connect(destination) as con:
                    self.assertEqual(con.execute('SELECT name FROM opportunities').fetchone()[0], 'عميل')
                with self.assertRaises(FileExistsError): backup.backup(app.DB, destination)
                with self.assertRaises(ValueError): backup.backup(app.DB, app.DB)
                with self.assertRaises(ValueError): backup.backup(Path(directory)/'missing', Path(directory)/'new')
                self.assertFalse((Path(directory)/'new').exists())
            finally: app.DB = old

class HttpTests(unittest.TestCase):
    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.tmp.name) / 'http.sqlite3'
        app.init_db()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.DB = self.old_db
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        import http.client
        con = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            con.request(method, path, body=body, headers=headers or {})
            response = con.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            con.close()

    def test_api_calendar_and_origin(self):
        import json
        payload = json.dumps({'name':'عميل', 'due_date':'2026-11-06', 'next_action':'اتصال'}).encode()
        headers = {'Content-Type':'application/json'}
        status, _, body = self.request('POST', '/api/opportunities', payload, headers)
        self.assertEqual(status, 201)
        ident = json.loads(body)['id']
        status, headers, body = self.request('GET', '/api/calendar')
        self.assertEqual(status, 200)
        self.assertTrue(headers['Content-Type'].startswith('text/calendar'))
        self.assertIn('DTSTART;VALUE=DATE:20261106', body.decode())
        self.assertEqual(self.request('DELETE', '/api/opportunities/' + str(ident), headers={'Origin':'https://evil.example'})[0], 403)
        self.assertEqual(len(app.rows()), 1)
        self.assertEqual(self.request('DELETE', '/api/opportunities/' + str(ident))[0], 200)

    def test_authentication_covers_calendar(self):
        import base64
        from unittest.mock import patch
        with patch.dict('os.environ', {'AAMM_PASSWORD':'test-password'}):
            self.assertEqual(self.request('GET', '/api/calendar')[0], 401)
            token = base64.b64encode(b'aamm:test-password').decode()
            self.assertEqual(self.request('GET', '/api/calendar', headers={'Authorization':'Basic ' + token})[0], 200)

if __name__ == '__main__': unittest.main()
