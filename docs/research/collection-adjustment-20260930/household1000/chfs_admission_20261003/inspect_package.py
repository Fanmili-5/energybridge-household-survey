#!/usr/bin/env python3
"""Inventory the user-supplied CHFS package; retain source bytes in Downloads.

No respondent values or identifiers are printed or exported by this script.
Metadata and document extraction are kept outside the publishable output set.
"""
import hashlib
import json
from pathlib import Path
import pandas as pd
from pypdf import PdfReader
from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
PACKAGE = Path('/Users/fanmili/Downloads/2021')

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n')

def safe_text(s):
    return (s or '').encode('utf-8', 'replace').decode('utf-8')

def main():
    entries=[]
    for path in sorted(PACKAGE.rglob('*')):
        if not path.is_file():
            continue
        item={'original_local_path':str(path), 'package_relative_path':str(path.relative_to(PACKAGE)),
              'bytes':path.stat().st_size, 'sha256':sha(path),
              'provenance':'user-supplied download; external download URL and official-byte identity not supplied'}
        if path.suffix=='.dta':
            with pd.io.stata.StataReader(path, convert_categoricals=False) as reader:
                meta={'variable_labels':reader.variable_labels(),
                      'value_labels':{k:{str(c):v for c,v in vals.items()} for k,vals in reader.value_labels().items()}}
            write(HERE/'private_metadata'/f'{path.stem}_metadata.json', meta)
            item.update(variable_count=len(meta['variable_labels']), microdata_rows_exported=0)
        elif path.suffix=='.pdf':
            pdf=PdfReader(path)
            pages=[{'page_1based':i+1,'text':safe_text(p.extract_text())} for i,p in enumerate(pdf.pages)]
            write(HERE/'private_metadata'/f'{path.stem}_pages.json',pages)
            item.update(pages=len(pages),pages_with_text=sum(bool(p['text'].strip()) for p in pages))
        elif path.suffix=='.xlsx':
            wb=load_workbook(path,read_only=True,data_only=False)
            sheets={s.title:[[c for c in row] for row in s.iter_rows(values_only=True)] for s in wb}
            write(HERE/'private_metadata'/f'{path.stem}_sheets.json',sheets)
            item.update(sheets=[{'name':s.title,'rows':s.max_row,'columns':s.max_column} for s in wb])
            wb.close()
        entries.append(item)
    write(HERE/'PACKAGE_MANIFEST.json',{'batch_id':'CHFS_ADMISSION_20261003_V1',
          'date_HKT':'2026-10-03','entries':entries,'raw_rows_exported':0,
          'collection_release':False,'training_release':False,'script_sha256':sha(Path(__file__))})
    for path in sorted((HERE/'private_metadata').glob('*_metadata.json')):
        m=json.loads(path.read_text())
        selected={k:v for k,v in m['variable_labels'].items() if k in
                  ['hhid','pline','rural','istowns','category','wgt_hh','wgt_ind','a2000','a2000c','a2001','a2005','total_income','total_consump']}
        print(json.dumps({'file':path.name,'variable_count':len(m['variable_labels']),'selected_labels':selected},ensure_ascii=False))

if __name__=='__main__':
    main()
