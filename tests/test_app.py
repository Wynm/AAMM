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

if __name__ == '__main__': unittest.main()
