#!/usr/bin/env python3
"""Inspect a user-supplied CRECS archive; print only metadata, never rows.

2013 is inventoried but not loaded: its rural frame is outside the city target.
Source bytes are local and ignored by Git. No CFPS files are accessed.
"""
import hashlib
import io
import json
from pathlib import Path
import zipfile
import pandas as pd
from pypdf import PdfReader

HERE=Path(__file__).resolve().parent
ARCHIVE=Path('/Users/fanmili/Downloads/家庭能源消费调查.zip')
def sha(b):return hashlib.sha256(b).hexdigest()
def dec(n):
    try:return n.encode('cp437').decode('gb18030')
    except UnicodeError:return n
def label_text(t):
    if not isinstance(t,str):return str(t)
    try:
        candidate=t.encode('latin1').decode('gb18030')
        if sum('\u4e00'<=c<='\u9fff' for c in candidate)>sum('\u4e00'<=c<='\u9fff' for c in t):return candidate
    except UnicodeError:pass
    return t
def save(p,b):
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        assert p.read_bytes()==b, f'Existing bytes differ: {p.name}'
    else:p.write_bytes(b)
def write(p,x):save(p,(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

def main():
    rows=[]
    with zipfile.ZipFile(ARCHIVE) as outer:
        for f in outer.infolist():
            if f.is_dir():continue
            b=outer.read(f);display=dec(f.filename)
            if f.filename.endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(b)) as nested:
                    for g in nested.infolist():
                        if not g.is_dir():rows.append((display,dec(g.filename),nested.read(g)))
            else:rows.append((None,display,b))
    entries=[]
    for container,display,b in rows:
        year=next(y for y in [2012,2013,2014] if str(y) in display)
        ext=Path(display).suffix.lower()
        path=HERE/'private_raw'/f'CRECS{year}{ext}'
        entry={'year':year,'container':container,'original_display_name':display,
               'bytes':len(b),'sha256':sha(b),'format':ext,
               'provenance':'user-supplied download; original external download URL not provided',
               'local_file':str(path.relative_to(HERE))}
        if year==2013:
            entry['admission']='excluded_rural_scope';entry['microdata_read']=False
            entry.pop('local_file')
        else:
            save(path,b);entry['admission']='metadata_inspection_only_pending_field_semantics'
            if ext=='.dta':
                with pd.io.stata.StataReader(path,convert_categoricals=False) as reader:
                    metadata={'variable_labels':{str(k):label_text(v) for k,v in reader.variable_labels().items()},
                              'value_labels':{str(k):{str(c):label_text(v) for c,v in m.items()} for k,m in reader.value_labels().items()},
                              'label_decoding':'pandas native strings; recover GB18030 from Latin1 when Chinese-character coverage increases'}
                write(HERE/'private_metadata'/f'CRECS{year}_stata_metadata.json',metadata)
                entry['variable_count']=len(metadata['variable_labels'])
                entry['value_label_sets']=len(metadata['value_labels'])
                # Expose field labels only; no values from households.
                print(json.dumps({'year':year,'variables':metadata['variable_labels']},ensure_ascii=False))
            elif ext=='.pdf':
                pdf=PdfReader(path)
                pages=[{'page_1based':i+1,'text':p.extract_text() or ''} for i,p in enumerate(pdf.pages)]
                write(HERE/'private_metadata'/f'CRECS{year}_questionnaire_pages.json',pages)
                entry['pages']=len(pages)
                entry['pages_with_text']=sum(bool(p['text'].strip()) for p in pages)
                print(json.dumps({'year':year,'pdf_pages':entry['pages'],'pages_with_text':entry['pages_with_text'],'first_page_text':pages[0]['text'][:1800]},ensure_ascii=False))
        entries.append(entry)
    out={'batch_id':'CRECS_ADMISSION_20261003_V1','date_HKT':'2026-10-03',
         'archive':{'path':str(ARCHIVE),'bytes':ARCHIVE.stat().st_size,'sha256':sha(ARCHIVE.read_bytes())},
         'entries':entries,'raw_rows_exported':0,'profiles_generated':0,
         'collection_release':False,'code_sha256':sha(Path(__file__).read_bytes())}
    write(HERE/'PACKAGE_MANIFEST.json',out)

if __name__=='__main__':main()
