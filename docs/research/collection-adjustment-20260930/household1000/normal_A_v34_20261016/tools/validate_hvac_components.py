"""Validate emitted component object fields against the pinned EP schema.

This validates object structure/values, not whole-IDF node connectivity or
physical performance. It deliberately does not import the component generator.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import jsonschema
from common import OUT,EP_SCHEMA,read,rules_id,save,sha

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=1000);args=parser.parse_args()
    signature=rules_id();run=OUT/'runs'/signature[:16];records=[read(p)for p in sorted((run/'records').glob('*.json'))][:args.limit]
    schema=read(EP_SCHEMA)['properties'];failures=[];objects=0;units=0;validators={}
    for record in records:
        if not record['passed']:continue
        path=OUT/record['HVAC_components_path']
        if sha(path)!=record['HVAC_components_sha256']:raise ValueError('COMPONENT_BYTES_CHANGED')
        for package in read(path):
            units+=1
            for row in package['rows']:
                kind=row[0];definition=schema[kind];body_schema=next(iter(definition['patternProperties'].values()));fields=definition['legacy_idd']['fields'];body={}
                for index,value in enumerate(row[2:],2):
                    if value=='':continue
                    key=fields[index-1];prop=body_schema['properties'][key]
                    numeric=prop.get('type')in('number','integer')or any(p.get('type')in('number','integer')for p in prop.get('anyOf',[]))
                    if numeric:
                        try:value=float(value)
                        except ValueError:pass
                    body[key]=value
                if kind not in validators:validators[kind]=jsonschema.Draft7Validator(body_schema)
                for error in validators[kind].iter_errors(body):failures.append({'household_id':record['household_id'],'object_type':kind,'name':row[1],'error':error.message})
                objects+=1
    report={'rules_sha256':signature,'households_checked':len(records),'HVAC_units_checked':units,'objects_checked':objects,
            'passed':not failures,'failures':failures,'schema_sha256':sha(EP_SCHEMA),'validator_script_sha256':sha(__file__),
            'validation_scope':'component object fields and values only;whole occupied IDF and physical delivery pending','EP_started':0}
    save(OUT/'review/HVAC_COMPONENT_SCHEMA_REVIEW.json',report);print({k:v for k,v in report.items()if k!='failures'})
    if failures:print(failures[:10]);raise SystemExit(2)

if __name__=='__main__':main()
