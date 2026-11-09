"""Report native active curve observations against pinned source grids.

These are reported timestep observations, not every internal curve call.
An observed excursion is sufficient to reject a scientific result; absence
of excursions does not establish empirical product validation.
"""
import numpy as np

from .common import ROOT, digest, locked, read, require


def reviewed_policy(reference,tables,rows,fields,*,root=ROOT):
    """Accept only the unchanged, explicitly published indoor cooling rule."""
    policy=read(locked(reference,root))
    require(policy['schema']=='national_idf.public_cooling_wetbulb_method.v1'
        and policy['method']=='source_defined_constant_indoor_cooling_correction'
        and policy['boundary_F']==[57.,72.] and policy['source_grid_values_F']==[57.,67.,72.]
        and policy['allow_outdoor_extrapolation'] is False
        and policy['allow_heating_indoor_extrapolation'] is False
        and policy['model_parameters_or_table_limits_changed'] is False,'CURVE_SOURCE_METHOD_POLICY')
    code=locked(policy['source_code'],root).read_text()
    locked(policy['standard_pdf'],root)
    text=' '.join(locked(policy['standard_text'],root).read_text().split())
    require('indoor_t = [57.0, rated_t_i, 72.0]' in code and
        'Cooling variations shall be held constant for Tiwb less than 57°F and greater than 72°F' in code
        and 'Cooling variations shall be held constant' in text and '57°F' in text and '72°F' in text,
        'CURVE_SOURCE_METHOD_NOT_DOCUMENTED')
    objects={(r[0],r[1]):r for r in rows if len(r)>1};allowed=set()
    for name,table in tables.items():
        actual=objects.get(('Table:Lookup',name))
        require(actual is not None and digest(actual)==table['source_row_sha256'],'CURVE_METHOD_TABLE_CHANGED',name)
        if 'Cool-' not in name:continue
        for index,axis in enumerate(table['axes']):
            if index!=0 or 'wet_bulb_temp_in' not in axis['name']:continue
            row=objects.get(('Table:IndependentVariable',axis['name']))
            require(row is not None and fields.get(row,'extrapolation_method')=='Constant'
                and axis['extrapolation']=='Constant','CURVE_METHOD_EXTRAPOLATION_CHANGED')
            require([float(v) for v in row[11:]]==axis['grid_values'],'CURVE_METHOD_ACTUAL_GRID_CHANGED')
            expected=[(v-32)*5/9 for v in policy['source_grid_values_F']]
            require(len(axis['grid_values'])==3 and all(abs(a-b)<1e-10 for a,b in zip(axis['grid_values'],expected)),
                    'CURVE_METHOD_INDOOR_GRID_CHANGED')
            allowed.add((name,index))
    require(allowed,'CURVE_METHOD_NO_MATCHING_INDOOR_AXIS')
    return allowed


def classify_observations(observations,allowed=()):
    outside=sum(a['reported_outside_grid_observations'] for v in observations.values() for a in v)
    reviewed=sum(a['reported_outside_grid_observations'] for name,v in observations.items()
                 for i,a in enumerate(v) if (name,i) in allowed)
    return {'observed_outside_count':outside,'reviewed_source_method_use_count':reviewed,
        'unreviewed_outside_count':outside-reviewed,'passed_observed_domain_screen':outside==reviewed,
        'source_grid_limits_modified':False,'empirical_product_performance_validated':False}


def assess(tables,get,*,reviewed_axes=()):
    axes=[]
    for name,table in tables.items():
        mode='Heating' if 'Heat-' in name else 'Cooling'
        coil='HP_AC_mshp '+('htg' if mode=='Heating' else 'clg')+' coil'
        electricity=np.asarray(get(mode+' Coil Electricity Energy',coil,'J'))
        output=np.asarray(get('Performance Curve Output Value',name,'1'))
        active=(electricity>0)&(output>0)
        require(np.isfinite(electricity).all() and np.isfinite(output).all(),'CURVE_OBSERVATION_NONFINITE')
        for index,axis in enumerate(table['axes'],1):
            values=np.asarray(get(f'Performance Curve Input Variable {index} Value',name,''))
            require(values.shape==active.shape and np.isfinite(values).all(),'CURVE_OBSERVATION_SHAPE_OR_VALUE')
            low,high=axis['grid_range'];bad=active&((values<low)|(values>high))
            axes.append({'curve':name,'axis':axis['name'],'source_grid_range':axis['grid_range'],
                'active_observations':int(active.sum()),'outside_observations':int(bad.sum()),
                'reviewed_source_method_applies':(name,index-1) in reviewed_axes,
                'active_input_range':[float(values[active].min()),float(values[active].max())] if active.any() else None})
    require(axes,'CURVE_SUPPORT_TABLES_MISSING')
    count=sum(a['outside_observations'] for a in axes)
    reviewed=sum(a['outside_observations'] for a in axes if a['reviewed_source_method_applies'])
    return {'schema':'national_idf.native_curve_domain_quality.v1','observed_outside_count':count,
        'reviewed_source_method_use_count':reviewed,'unreviewed_outside_count':count-reviewed,
        'passed_observed_domain_screen':count==reviewed,'axes':axes,
        'observations_are_not_unique_minutes_or_all_internal_curve_calls':True,
        'empirical_product_performance_validated':False,'source_grid_limits_modified':False}
