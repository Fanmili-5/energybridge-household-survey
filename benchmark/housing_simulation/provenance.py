"""Check that contract fields, rules, sources, code symbols and document anchors connect."""
import ast
import json
from pathlib import Path
import re


def check_links(root):
    root=Path(root)
    read=lambda name:json.loads((root/name).read_text())
    sources={x['id']for x in read('SOURCES.json')['sources']}
    rules={x['id']:x for x in read('RULES.json')['rules']}
    def implementation(target):
        file,symbol=target.split(':',1)
        tree=ast.parse((root/file).read_text())
        if symbol not in {n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}:
            raise ValueError('unknown implementation symbol:'+target)
    for rule in rules.values():
        if not set(rule['sources'])<=sources:raise ValueError('unknown source:'+rule['id'])
        if {r['source_id']for r in rule['source_relations']}!=set(rule['sources']):
            raise ValueError('source relation coverage:'+rule['id'])
        implementation(rule['implementation'])
        file,anchor=rule['documentation'].split('#',1)
        anchors={re.sub(r'[^\w\s-]','',h.lower()).replace(' ','-')for h in re.findall(r'^#{1,6} (.+)$',(root/file).read_text(),re.M)}
        if anchor not in anchors:raise ValueError('missing document anchor:'+rule['documentation'])
    for item in read('ASSUMPTIONS.json')['entries']:
        if not set(item['sources'])<=sources:raise ValueError('unknown assumption source:'+item['id'])
        implementation(item['implementation'])
    schema=read('WORLD.schema.json');declared={f['schema_pointer']:f for f in read('FIELD_MAP.json')['fields']};seen={}
    def walk(node,path=''):
        if isinstance(node,dict):
            for name,value in node.get('properties',{}).items():
                pointer=path+'/properties/'+name
                ids=value.get('x-rule-ids',[])
                if not ids or not set(ids)<=rules.keys():raise ValueError('unmapped schema property:'+pointer)
                if value.get('x-evidence-class')not in ('interface_contract','declared_input'):raise ValueError('unclassified input:'+pointer)
                seen[pointer]={'schema_pointer':pointer,'rule_ids':ids,'evidence_class':value['x-evidence-class']}
            for key,value in node.items():
                if not key.startswith('x-'):walk(value,path+'/'+key)
        elif isinstance(node,list):
            for i,value in enumerate(node):walk(value,path+'/'+str(i))
    walk(schema)
    if seen!=declared:raise ValueError('FIELD_MAP/schema coverage mismatch')
    return {'mapped_schema_properties':len(seen),'rules':len(rules),'sources':len(sources)}
