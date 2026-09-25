"""EnergyPlus 24.1 may store non-warmup Time.WarmupFlag as NULL."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import native_assets
import paired_ep


class SqlNullWarmupTests(unittest.TestCase):
    def test_both_readers_keep_regular_rows_with_null_warmup_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            conn = sqlite3.connect(folder / 'eplusout.sql')
            conn.executescript('''
                CREATE TABLE ReportDataDictionary (
                  ReportDataDictionaryIndex INTEGER, Name TEXT, KeyValue TEXT,
                  Units TEXT, ReportingFrequency TEXT);
                CREATE TABLE Time (
                  TimeIndex INTEGER, Month INTEGER, Day INTEGER, Hour INTEGER,
                  Minute INTEGER, Interval INTEGER, WarmupFlag INTEGER);
                CREATE TABLE EnvironmentPeriods (EnvironmentPeriodIndex INTEGER, EnvironmentType INTEGER);
                CREATE TABLE ReportData (
                  ReportDataDictionaryIndex INTEGER, TimeIndex INTEGER,
                  EnvironmentPeriodIndex INTEGER, Value REAL);
                INSERT INTO ReportDataDictionary VALUES
                  (1,'Zone Mean Air Temperature','1-N-1','C','Zone Timestep');
                INSERT INTO EnvironmentPeriods VALUES (1,3);
                INSERT INTO Time VALUES (1,7,15,1,0,60,NULL);
                INSERT INTO ReportData VALUES (1,1,1,25.0);
            ''')
            conn.close()
            expected = {'Zone Mean Air Temperature|1-N-1': [
                {'end_h': 1.0, 'start_h': 0.0, 'value': 25.0, 'unit': 'C'}]}
            self.assertEqual(native_assets.read_series(folder, horizon=24, start_date='2013-07-15'), expected)
            self.assertEqual(paired_ep.read_series(folder, horizon=24, start_date='2013-07-15'), expected)


if __name__ == '__main__':
    unittest.main()
