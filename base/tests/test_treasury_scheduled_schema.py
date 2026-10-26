"""New installs keep Treasury scheduled rows independent of People."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from base.core import load, sql_schema

class TreasuryScheduledSchemaTests(unittest.TestCase):
    def test_no_people_foreign_key_in_blueprint_or_generated_schema(self):
        targets, columns = load(ROOT / 'base/blueprint')
        table = next(row for row in targets if row['name'] == 'treasury_scheduled_transactions')
        opportunity = next(row for row in columns if row['table'] == table['name'] and row['column'] == 'opportunity')
        self.assertEqual(opportunity['field_type'], 'integer')
        self.assertIsNone(opportunity['link'])
        self.assertFalse(any(row['table'] == 'people_opportunities' for row in table['foreign_keys']))
        for schema in (sql_schema(targets, columns), (ROOT / 'base/schema.sql').read_text()):
            statement = schema.split('CREATE TABLE "treasury_scheduled_transactions"', 1)[1].split(') STRICT;', 1)[0]
            self.assertIn('"opportunity" INTEGER', statement)
            self.assertNotIn('REFERENCES "people_opportunities"', statement)
            self.assertIn('REFERENCES "treasury_recurring_series"', statement)
            self.assertIn('REFERENCES "treasury_transactions"', statement)

if __name__ == '__main__':
    unittest.main()
