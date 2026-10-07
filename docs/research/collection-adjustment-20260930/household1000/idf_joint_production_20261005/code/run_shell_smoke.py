"""Runtime coverage for every byte-unique reference shell, including glazing.

One July day in the same Beijing EPW is a compiler/runtime witness. It is not
weather matching, annual energy, calibrated loads, or installed services.
"""
import concurrent.futures,json,re,sqlite3,subprocess
from collections import defaultdict,Counter
from compile_reference_idfs import OUT,ENGINE,EPW,sha,save

def main():
    bindings=json.loads((OUT/'IDF_REFERENCE_BINDINGS1000.json').read_text())['bindings']
    groups=defaultdict(list)
    for b in bindings:groups[b['IDF_sha256']].append(b)
    def run(group):
        b=group[0];p=OUT/b['IDF_path'];d=OUT/'shell_runtime'/b['household_id'];d.mkdir(parents=True,exist_ok=True)
        r=subprocess.run([str(ENGINE),'-w',str(EPW),'-d',str(d),str(p)],capture_output=True,text=True,timeout=120)
        (d/'console.txt').write_text(r.stdout+'\n'+r.stderr)
        err=(d/'eplusout.err').read_text() if (d/'eplusout.err').exists() else ''
        messages=re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err)
        severe=len(re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*',err))
        if r.returncode or severe:raise RuntimeError(str(d/'eplusout.err'))
        db=sqlite3.connect(d/'eplusout.sql');n=db.execute('SELECT COUNT(*) FROM ReportDataDictionary WHERE Name=?',('Zone Mean Air Temperature',)).fetchone()[0];db.close()
        assert n==b['Zone_count']
        return {'representative_household_id':b['household_id'],'bound_households':[q['household_id'] for q in group],
                'input_IDF_sha256':sha(p),'SQL_sha256':sha(d/'eplusout.sql'),'returncode':r.returncode,
                'severe_or_fatal':severe,'warnings':messages,'zone_temperature_dictionary_entries':n,
                'run_path':str(d.relative_to(OUT)),'runperiod':'2007-07-01 to2007-07-01,24h plus engine warmup'}
    with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(run,groups.values()))
    report={'cases':results,'byte_unique_reference_shells_run':len(results),
            'population_IDF_bindings_covered':sum(len(r['bound_households']) for r in results),
            'total_warning_entries':sum(len(r['warnings']) for r in results),'severe_or_fatal':0,
            'EPW_path':str(EPW),'EPW_sha256':sha(EPW),'engine_sha256':sha(ENGINE),
            'glazing_solar_and_original_wall_IR_included_in_runtime':True,
            'free_floating_empty_reference_shells_not_household_energy_models':True,
            'actual_household_weather_or_annual_energy_validated':False,'empirical_glazing_or_floor_response_validated':False,
            'warning_messages':dict(Counter(m for r in results for m in r['warnings']))}
    save(OUT/'SHELL_RUNTIME_COVERAGE.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ['cases','warning_messages']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
