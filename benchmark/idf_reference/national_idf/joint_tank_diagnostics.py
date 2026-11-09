"""Read-only observations for the existing six-device CASE runtime."""
import csv
from pathlib import Path
from .common import read,require,save,sha
from .idf import objects
from .stratified_storage import SourceWaterProperties,StratifiedStorageObserver,PostResetStorageBalance,THERMAL_OUTPUTS
from .water_service import WaterServiceObserver

class JointTankDiagnostics:
    def open(self,out,rows,fields,spec,root):
        tank=next(r for r in objects(rows,'WaterHeater:Stratified') if r[1]==spec['EB_mapping']['water_heater'])
        source=root/'data/source/stratified_energy_20261030'
        props=SourceWaterProperties((source/'FluidProperties.cc').read_text(),(source/'DataGlobalConstants.hh').read_text())
        self.observer=StratifiedStorageObserver(tank[1],float(fields.get(tank,'tank_volume')),int(fields.get(tank,'number_of_nodes')),props)
        protocol=read(root/'configs/study_protocol.json')
        self.post_reset=PostResetStorageBalance(self.observer,protocol['comparison_grid_min']*60)
        self.service=WaterServiceObserver([r[1] for r in objects(rows,'WaterUse:Equipment')])
        self.stream=(out/'SYSTEM_STORAGE.csv').open('w',newline='')
        self.writer=csv.DictWriter(self.stream,fieldnames=['elapsed_s','dt_s',*THERMAL_OUTPUTS,'storage_change_J','external_sum_J','storage_residual_J',*[f'node_{i}_C' for i in range(1,self.observer.nodes+1)]])
        self.writer.writeheader()
        self.sources={str(p.relative_to(root)):sha(p) for p in (source/'FluidProperties.cc',source/'DataGlobalConstants.hh')}
    def request_outputs(self,exchange,state):
        self.observer.request_outputs(exchange,state);self.service.request_outputs(exchange,state)
    def initialize(self,exchange,state):
        self.observer.initialize(exchange,state);self.service.initialize(exchange,state)
    def begin(self,exchange,state):
        if self.observer.previous_temperatures is None:self.observer.begin(exchange,state)
    def observe_system(self,exchange,state):
        seconds=exchange.system_time_step(state)*3600
        row=self.observer.observe_system(exchange,state,seconds)
        self.post_reset.observe(row,self.observer.seconds)
        self.service.observe_system(exchange,state,seconds)
        self.writer.writerow({'elapsed_s':self.observer.seconds,**row})
    def close(self):self.stream.close()
    def report(self,out,timeline):
        require(abs(self.observer.seconds-timeline.days*86400)<1e-4,'SIX_STORAGE_OBSERVATION_DURATION')
        storage=self.observer.report()
        storage['post_reset_common_interval']=self.post_reset.report()
        storage['full_period_initial_storage_not_measured']=True
        save(out/'STORAGE_BALANCE.json',storage);save(out/'WATER_SERVICE.json',self.service.report())
        return {'read_only':True,'system_seconds':self.observer.seconds,'official_water_property_sources':self.sources,
                'diagnostic_implementation':{name:sha(Path(__file__).parent/name)
                    for name in ('joint_tank_diagnostics.py','stratified_storage.py')},
                'first_pre_reset_state_is_not_full_period_initial_energy':True,'formal_admitted':False}
