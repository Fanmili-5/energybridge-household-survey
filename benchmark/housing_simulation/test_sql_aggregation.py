"""Cumulative water volume is summed like energy; temperatures are averaged."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from .pipeline import sql_trace


class NativeAggregationTests(unittest.TestCase):
    def test_dictionary_type_controls_aggregation_instead_of_energy_unit(self):
        with tempfile.TemporaryDirectory()as temp:
            p=Path(temp)/'native.sql'
            with sqlite3.connect(p)as db:
                db.executescript('''CREATE TABLE ReportDataDictionary(ReportDataDictionaryIndex INTEGER,Name TEXT,KeyValue TEXT,Units TEXT,IsMeter INTEGER,Type TEXT);
                CREATE TABLE Time(TimeIndex INTEGER,SimulationDays INTEGER,Hour INTEGER,Minute INTEGER,Interval INTEGER,WarmupFlag INTEGER,EnvironmentPeriodIndex INTEGER);
                CREATE TABLE EnvironmentPeriods(EnvironmentPeriodIndex INTEGER,EnvironmentType INTEGER);
                CREATE TABLE ReportData(ReportDataDictionaryIndex INTEGER,TimeIndex INTEGER,Value REAL);''')
                db.execute('INSERT INTO EnvironmentPeriods VALUES(1,3)')
                db.executemany('INSERT INTO Time VALUES(?,1,0,?,5,0,1)',[(1,5),(2,10)])
                specs=[('Electricity:Facility','','J',1,'Sum',[5,7]),('Zone Mean Air Temperature','ROOM','C',0,'Avg',[20,24]),('Water Use Equipment Total Volume','SHOWER','m3',0,'Sum',[.01,.02])]
                for i,(name,key,unit,meter,kind,values)in enumerate(specs,1):
                    db.execute('INSERT INTO ReportDataDictionary VALUES(?,?,?,?,?,?)',(i,name,key,unit,meter,kind))
                    db.executemany('INSERT INTO ReportData VALUES(?,?,?)',[(i,j,v)for j,v in enumerate(values,1)])
            trace=sql_trace(p,0,5)
            self.assertEqual(trace['Electricity:Facility|']['values'],[[0,12]])
            self.assertEqual(trace['Zone Mean Air Temperature|ROOM']['values'],[[0,22]])
            self.assertAlmostEqual(trace['Water Use Equipment Total Volume|SHOWER']['values'][0][1],.03)


if __name__=='__main__':unittest.main()
