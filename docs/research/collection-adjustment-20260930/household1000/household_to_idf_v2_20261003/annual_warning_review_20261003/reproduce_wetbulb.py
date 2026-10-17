# Diagnostic equations transcribed from EnergyPlus version 24.1.0 mathematical
# definitions. Official source URLs, byte hashes and limitations are recorded
# in ../ANNUAL_WARNING_REVIEW.json. This is a research stress translation, not
# an EnergyPlus implementation, patch, complete engine reproduction or fix.
# No IDF, EPW, engine output or compiler file is edited.
"""Read-only diagnostic translation of E+24.1 equations, not an engine replacement."""
import math,struct,csv,pathlib,json

def quant(x,bits):
 u=struct.unpack('Q',struct.pack('d',x))[0];shift=52-bits
 return struct.unpack('d',struct.pack('Q',(u>>shift)<<shift))[0]
def psat(t):
 t=quant(t,24);k=t+273.15
 if k<173.15:return .001405102123874164
 if k<273.16:return math.exp(-5674.5359/k+6.3925247+k*(-.009677843+k*(.00000062215701+k*(.0000000020747825-.0000000000009484024*k)))+4.1635019*math.log(k))
 if k<=473.15:return math.exp(-5800.2206/k+1.3914993+k*(-.048640239+k*(.000041764768-.000000014452093*k))+6.5459673*math.log(k))
 return 1555073.745636215

def step(x,y,x1,y1,i):
 if i!=1 and (abs(x-x1)<.0001 or y==0):return x,True,x1,y1
 if i==1:r=x*1.1 if abs(x)>1e-9 else .1
 else:
  dy=y-y1
  if abs(dy)<1e-9:dy=1e-9
  r=(y*x1-y1*x)/dy
 return r,False,x,y

def boiling(p):
 x=100.;x1=y1=0.
 for i in range(1,51):
  y=p-psat(x);x,done,x1,y1=step(x,y,x1,y1,i)
  if done:return x
 return x

def neww(tdb,wb,p):
 ws=.62198*psat(wb)/(p-psat(wb))
 if wb>=0:return ((2501-2.326*wb)*ws-1.006*(tdb-wb))/(2501+1.86*tdb-4.186*wb)
 return ((2830-.24*wb)*ws-1.006*(tdb-wb))/(2830+1.86*tdb-2.1*wb)

def solve(tdb,rh,p):
 w=max(1e-5,.62198*(rh*psat(tdb))/max(p-rh*psat(tdb),1000.))
 tdb,w,p=map(lambda x:quant(x,20),(tdb,w,p));wb=tdb;x1=y1=0.;tb=boiling(p);trace=[]
 for i in range(1,101):
  if wb>=tb-.09:wb=tb-.1
  y=w-neww(tdb,wb,p);trace.append({'iteration':i,'wetbulb_trial_C':wb,'psat_argument_C':quant(wb,24),'humidity_ratio_error':y})
  wb,done,x1,y1=step(wb,y,x1,y1,i)
  if done:break
 return {'cached_input_tdb_C':tdb,'cached_input_W':w,'cached_input_P_Pa':p,'converged':done,'iterations':i,'result_Twb_C':min(wb,tdb),
  'out_of_range_trials':[r for r in trace if r['psat_argument_C']<=-100 or r['psat_argument_C']>=200],
  'trace':trace,'boiling_C':tb}

def fractions(epw,mdh):
 rr=list(csv.reader(epw.open()))[8:];i=next(i for i,r in enumerate(rr) if tuple(map(int,r[1:4]))==mdh)
 prev,curr=rr[i-1],rr[i]
 results=[]
 for f in [.25,.5,.75,1.]:
  values=[float(prev[k])*(1-f)+float(curr[k])*f for k in [6,8,9]]
  results.append({'previous_EPW_line':i+8,'current_EPW_line':i+9,'current_hour_weight':f,'original_interpolated_tdb_RHpct_P':values,'solution':solve(values[0],values[1]/100,values[2])})
 return results

if __name__=='__main__':
 root=pathlib.Path('/Users/fanmili/studytest/energybridge-household-survey/docs/research/collection-adjustment-20260930/household1000/household_to_idf_v2_20261003')
 output=[]
 for key,mdh in [('v2_bj_2011_2025',(4,6,5)),('v2_nm_2011_2025',(5,4,21)),('v2_qh_2011_2025',(3,6,14)),('v2_qh_2011_2025',(3,6,16))]:
  results=fractions(root/'weather_resources'/key/'weather.epw',mdh)
  output.append({'weather':key,'EPW_MDH':mdh,'quarter_inputs':results})
  for r in results:
   s=r['solution'];print(key,mdh,r['current_hour_weight'],s['cached_input_tdb_C'],s['cached_input_W'],s['cached_input_P_Pa'],s['converged'],s['result_Twb_C'],s['out_of_range_trials'])
 pathlib.Path('/private/tmp/eplus24_warning_source/WETBULB_STRESS.json').write_text(json.dumps(output,indent=2)+'\n')
