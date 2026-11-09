"""Read authorized minimal fields without turning reference values into facts."""
import copy
from collections import Counter

from .common import ROOT, read, require
from .reference_scenarios import FUNCTIONS, resolve
from .source_adapter import source_file

ROW_FIELDS={'case_id_sha256_prefix','country','dwelling','equipment','asset_registry','shared_asset_constraints'}
FORMS={
    'detached_house':'detached', 'Single-family house detached from any other house':'detached',
    'independent_house_or_bungalow':'detached', 'attached_house':'attached',
    'Single-family house attached to one or more other houses (for example: duplex, row or terraced house, or townhome)':'attached',
    'Apartment in a building with 2 to 5 flats':'apartment','Apartment in a building with 6 or more flats':'apartment',
    'multi_storey_apartment':'apartment','flat':'apartment','apartment':'apartment',
    'small_apartment_building':'apartment','large_apartment_building':'apartment'}


def request_from_projection(row,projection_ref):
    require(set(row)==ROW_FIELDS,'HOUSEHOLD_PROJECTION_UNEXPECTED_FIELD')
    require(set(row['equipment'])==set(FUNCTIONS),'HOUSEHOLD_PROJECTION_FUNCTIONS')
    equipment={};gaps=[]
    for key,entry in row['equipment'].items():
        present=entry['reference_physically_present'];enabled=entry['control_enabled']
        require(type(present) is bool or present is None,'HOUSEHOLD_PROJECTION_PRESENCE_TYPE')
        require(type(enabled) is bool,'HOUSEHOLD_PROJECTION_CONTROL_TYPE')
        if entry.get('equipment_entry_control_enabled')!=enabled:
            gaps.append({'code':'UPSTREAM_CONTROL_FLAGS_CONFLICT','function':key})
        asset_candidates={entry[k] for k in ('reference_asset_id','equipment_asset_id') if entry.get(k)}
        registry=[a for a in row['asset_registry'] if key in a['functions']]
        asset_candidates.update(a['asset_id'] for a in registry if a['asset_id'])
        if len(asset_candidates)>1 or present is True and len(asset_candidates)!=1:
            gaps.append({'code':'UPSTREAM_ASSET_MISSING_OR_CONFLICT','function':key})
        # Missing asset stays unknown; it is never replaced with a fabricated
        # machine identifier to make an operational configuration pass.
        asset=next(iter(asset_candidates)) if len(asset_candidates)==1 else None
        fixed=any(key in a['fixed_functions'] for a in registry)
        background=('upstream_fixed_function:'+asset+':'+key) if asset and fixed else None
        if present and not enabled:
            gaps.append({'code':'FIXED_BACKGROUND_SERVICE_SCHEDULE_NOT_PROJECTED','function':key})
            if not background:gaps.append({'code':'UPSTREAM_FIXED_SERVICE_ASSET_LINK_MISSING','function':key})
        equipment[key]={'physically_present':present,'control_enabled':enabled,'asset_id':asset,
                        'presence_basis':'Upstream declared reference equipment; source_presence retained separately',
                        'background_service_id':background,'source_presence':copy.deepcopy(entry['source_presence'])}
    dwelling=copy.deepcopy(row['dwelling'])
    request={'schema':'national_idf.reference_scenario_request.v1','purpose':'roleplay_control_reference',
             'request_id':'projected-'+row['case_id_sha256_prefix'],'country':row['country'],
             'source_input_receipt':projection_ref,
             'survey_dwelling':{'source_size_measure':dwelling['source_size_measure'],
                                'area_m2':None,'type':None,
                                'reason':'No field-level evidence here that upstream reference area/type is a survey measurement'},
             'upstream_reference_dwelling':dwelling,
             'reference_selection':{},'equipment':equipment}
    return request,gaps


def screen(projection_ref,catalog_ref,*,root=ROOT):
    projection=read(source_file(projection_ref,root))
    require(projection['schema']=='national_idf.household_interface_projection.v1','HOUSEHOLD_PROJECTION_SCHEMA')
    require(projection['source_receipt']['read_only'] is True,'HOUSEHOLD_PROJECTION_NOT_READ_ONLY')
    country_counts=Counter();inventories=Counter();controls=Counter();gap_counts=Counter();per_household=[]
    catalog=read(source_file(catalog_ref,root));source_shared=0
    for row in projection['households']:
        request,gaps=request_from_projection(row,projection_ref)
        country_counts[row['country']]+=1
        installed=tuple(k for k in FUNCTIONS if row['equipment'][k]['reference_physically_present'] is True)
        controlled=tuple(k for k in FUNCTIONS if row['equipment'][k]['control_enabled'])
        inventories[(row['country'],installed)]+=1;controls[len(controlled)]+=1
        source_shared+=bool(row['shared_asset_constraints'])
        # Input gaps are reported before operational matching. A declared
        # fixed asset link is not a personal schedule and does not supply one.
        can_screen=not any(g['code'] in ('UPSTREAM_ASSET_MISSING_OR_CONFLICT','UPSTREAM_FIXED_SERVICE_ASSET_LINK_MISSING',
                                         'UPSTREAM_CONTROL_FLAGS_CONFLICT') for g in gaps)
        result=resolve(request,catalog_ref,root=root) if can_screen else None
        if result:
            form=FORMS.get(row['dwelling']['type'])
            for candidate in result['reference_candidates']:
                cls=candidate['reference_dwelling']['housing_class']
                source_form='apartment' if 'apartment' in cls else 'detached' if 'detached' in cls else None
                candidate['upstream_reference_form']=form
                candidate['basic_form_agrees_with_upstream_design']=form==source_form if form and source_form else None
                candidate['source_area_minus_upstream_reference_m2']=(candidate['reference_dwelling']['area_m2']-
                    row['dwelling']['reference_area_m2']) if type(row['dwelling']['reference_area_m2']) in (int,float) else None
                candidate['no_implicit_area_resize_or_reference_rewrite']=True
        if not any(r['country']==row['country'] for r in catalog['records']):gaps.append({'code':'COUNTRY_PARAMETER_PACKAGE_NOT_REGISTERED'})
        signatures=[set(r['installed_devices']) for r in catalog['records'] if r['country']==row['country']]
        if signatures and set(FUNCTIONS[k] for k in installed) not in signatures:
            gaps.append({'code':'PHYSICAL_INVENTORY_VARIANT_NOT_BUILT','functions':list(installed)})
        for gap in gaps:gap_counts[gap['code']]+=1
        per_household.append({'case_id_sha256_prefix':row['case_id_sha256_prefix'],'country':row['country'],
                              'physical_functions':list(installed),'controlled_functions':list(controlled),
                              'upstream_reference_dwelling':request['upstream_reference_dwelling'],
                              'survey_dwelling':request['survey_dwelling'],
                              'shared_asset_constraints':copy.deepcopy(row['shared_asset_constraints']),
                              'input_gaps':gaps,'reference_resolution':result,
                              'formal_binding':None,'source_modified':False})
    return {'schema':'national_idf.projected_household_reference_screen.v1','source_projection':projection_ref,
            'source_status':'candidate_input_access_authorized_not_adopted_as_formal_batch',
            'country_counts':dict(country_counts),'controlled_function_counts':dict(controls),
            'physical_inventory_groups':[{'country':country,'functions':list(functions),'rows':count}
                                         for (country,functions),count in sorted(inventories.items())],
            'shared_asset_rows':source_shared,'input_gap_counts':dict(gap_counts),
            'records':per_household,'formal_bindings':0,'national_or_household_coverage_rate':None,
            'households_generated':False,'household_or_AB_modified':False}
