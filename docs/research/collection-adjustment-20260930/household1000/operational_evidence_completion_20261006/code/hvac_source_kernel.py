"""Manufacturer-specific rated-frequency Q/P state kernel with domain guards.
Uses graph-native vectors and keeps graphical extraction precision, ISO5151
nameplate normalization, actual auto-inverter control and installation separate.
No Haier identity or annual measured efficiency is inferred from this kernel.
"""
import math,bisect
from common import *
MODELS={'MUZ-AP25VG':(2500.,600.),'MUZ-AP35VG':(3500.,990.),'MUZ-AP42VG':(4200.,1300.),'MUZ-AP50VG':(5000.,1550.)}
def curve(data,kind,wb,out):
 rows=data[kind]['curves'];levels=[r['indoor_WB_C'] for r in rows]
 if not math.isfinite(wb) or not math.isfinite(out) or not levels[0]<=wb<=levels[-1]:raise ValueError('outside_documented_indoor_WB_domain')
 if wb in levels:idx=[levels.index(wb)]
 else:j=bisect.bisect_right(levels,wb);idx=[j-1,j]
 vals=[]
 for i in idx:
  r=rows[i];x0,y0=r['temperature_factor_endpoints'][0];x1,y1=r['temperature_factor_endpoints'][1]
  if not x0<=out<=x1:raise ValueError('outside_traced_OEM_curve_support;noextrapolation_orclamping')
  vals.append(y0+(y1-y0)*(out-x0)/(x1-x0))
 if len(idx)==1:return vals[0]
 a,b=idx;return vals[0]+(vals[1]-vals[0])*(wb-levels[a])/(levels[b]-levels[a])
def evaluate(data,model,wb,out,operation='documented_rated_frequency'):
 if model not in MODELS:raise ValueError('source_model_identity_not_supported')
 if operation!='documented_rated_frequency':raise ValueError('automatic_inverter_governor_or_partload_not_validated')
 q,p=MODELS[model];cq=curve(data,'capacity_factor',wb,out)/data['capacity_factor']['normalization_at19WB35DB'];cp=curve(data,'total_input_factor',wb,out)/data['total_input_factor']['normalization_at19WB35DB']
 return {'cooling_capacity_W_reference':q*cq,'total_set_electric_input_W_reference':p*cp,'COP_reference_not_SEER':q*cq/(p*cp),'declared_graph_interpolation_not_exact_measured_household_performance':True}
def main():
 guard();ex=read(OUT/'HVAC_PDF_VECTOR_EXTRACTION.json');result={}
 for key,page,xzero,xspan,yone,ytick in [('capacity_factor',15,217.774,459.431-217.774,129.080,15.730),('total_input_factor',16,193.345,435.725-193.345,692.403,15.800)]:
  rows=next(x for x in ex['page_vector_data'] if x['PDF_page1based']==page)['candidate_performance_lines'];assert len(rows)==5;rows=sorted(rows,key=lambda r:r['vertices_pdfpoints'][0][1]);curves=[]
  for wb,r in zip([18.,20.,22.,24.,26.],rows):
   pp=[[55*(x-xzero)/xspan-10.,1.+.1*(y-yone)/ytick] for x,y in r['vertices_pdfpoints']]
   curves.append({'indoor_WB_C':wb,'temperature_factor_endpoints':pp,'PDF_vector_endpoints':r['vertices_pdfpoints']})
  result[key]={'PDF_page1based':page,'axis_calibration':{'outdoor_DB_minus10_pdfx':xzero,'outdoor_DB45_minus_minus10_pdf_span':xspan,'factor1_pdfy':yone,'factor0_1_pdf_dy':ytick},'curves':curves}
  result[key]['normalization_at19WB35DB']=curve(result,key,19.,35.)
 result.update({'primary_source':'raw/Mitsubishi_OBH789.pdf','PDF_sha256':sha(OUT/'raw/Mitsubishi_OBH789.pdf'),'nominal_specs_PDF_page1based':6,
  'nominal_ISO5151_conditions':{'indoor_DB_C':27.,'indoor_WB_C':19.,'outdoor_DB_C':35.,'outdoor_WB_C':24.,'piping_one_way_m':5.,'voltage_V':230.,'frequency_Hz':50.},
  'mode':'manufacturer rated-frequency performance only;not original automatic control','models':{k:{'capacity_W':q,'total_set_input_W':p,'COP_derived':q/p} for k,(q,p) in MODELS.items()},
  'graph_nameplate_normalization_is_explicit':True,'graphical_precision_not_equivalent_to_test_raw_measurements':True,'curves_not_relabelled_as_Haier':True,
  'no_generic_Lennox_rooftop_curve_borrowing':True,'kernel_alone_does_not_supply_indoor_fan_latent_map_or_auto_governor':True,
  'paired_indoor_parameters_and_aggregate_coupling_companion':'COUPLED_UNIFORM_MINUTE_BINDINGS.json',
  'kernel_is_not_full_refrigerant_airside_or_installed_HVAC_model':True})
 save(OUT/'HVAC_SOURCE_KERNEL.json',result)
 # Deterministic checks against rated anchors, monotonic outdoor effect within
 # traced support, and explicit forbidden state/model identities.
 checks=[]
 for model,(q,p) in MODELS.items():
  z=evaluate(result,model,19.,35.);assert abs(z['cooling_capacity_W_reference']-q)<1e-8 and abs(z['total_set_electric_input_W_reference']-p)<1e-8
  a,b=evaluate(result,model,20.,25.),evaluate(result,model,20.,35.);assert a['cooling_capacity_W_reference']>b['cooling_capacity_W_reference'] and a['total_set_electric_input_W_reference']<b['total_set_electric_input_W_reference'];checks.append({'model':model,'rated_anchor_and_direction_checked':True})
 negative=[]
 for name,args in [('wrongOEM',('Haier_KFR26',19.,35.)),('WB_as_outdoorDB',(next(iter(MODELS)),35.,19.)),('outside_chart',(next(iter(MODELS)),26.,45.)),('auto_inverter',(next(iter(MODELS)),19.,35.,'automatic_controller'))]:
  try:evaluate(result,*args);rejected=False
  except ValueError:rejected=True
  assert rejected;negative.append({'injection':name,'rejected':rejected})
 save(OUT/'HVAC_KERNEL_VERIFICATION.json',{'checks':checks,'negative_controls':negative,'domain_and_source_identity_guarded':True,
  'measured_validation_or_complete_HVAC_IDF_not_claimed':True})
 print({'source_models':len(MODELS),'OEM_graph_curves':10,'normalizers':{k:result[k]['normalization_at19WB35DB'] for k in ['capacity_factor','total_input_factor']},'negative_controls':4})
if __name__=='__main__':main()
