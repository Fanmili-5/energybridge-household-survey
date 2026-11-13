"""Interpret explicit CASE.v2 inputs; never create power profiles or routines.

Physical-domain review and source binding belong to the compiler. These frames
are input semantics only and cannot grant execution or appliance service proof.
"""
import copy
import datetime as dt

from .common import ROOT, digest, require
from .request_support import PROGRAMS, assess_inputs


class CaseTimeline:
    def __init__(self, case, domain, *, root=ROOT):
        self.case = copy.deepcopy(case)
        self.domain = copy.deepcopy(domain)
        self.support = assess_inputs(self.case, self.domain, root)
        require(self.support['inputs_supported'], 'CASE_COMMAND_INPUT_UNSUPPORTED', self.support['failures'])
        self.begin = dt.date.fromisoformat(case['run']['start_date'])
        self.end = dt.date.fromisoformat(case['run']['end_date'])
        self.step_min = domain['solver_step_min']
        require(self.step_min in (1, 2, 5) and 1440 % self.step_min == 0, 'CASE_COMMAND_STEP_UNSUPPORTED')
        self.days = (self.end - self.begin).days + 1
        self.steps = self.days * 1440 // self.step_min
        from .eb_water_heater_window import validate
        validate(case,domain)
        self.input_sha256 = digest({'case': self.case, 'domain': self.domain})
        self._dated_views={}
        if case.get('schema')=='national_idf.case.v3':
            from .dated_case import dates,view
            self._dated_views={d:view(case,d) for d in dates(case)}

    @staticmethod
    def within(minute, interval):
        return interval['start_min'] <= minute < interval['end_min']

    def _legacy_frame(self, index):
        require(type(index) is int and 0 <= index < self.steps, 'CASE_COMMAND_STEP_OUTSIDE_RUN', index)
        elapsed = index * self.step_min
        day, minute = divmod(elapsed, 1440)
        date = (self.begin + dt.timedelta(days=day)).isoformat()
        life, control = self.case['life'], self.case['controls']
        values = {key: control[key] for key in ('heating_C', 'cooling_C', 'hvac_available', 'tank_target_C', 'ev_target_SOC')}
        for override in control['daily_overrides'] + [r for r in control.get('dated_overrides', []) if r['date'] == date]:
            if self.within(minute, override):
                values[override['field']] = override['value']
        people = {zone: {'persons': 0, 'activity_total_W': 0, 'activity_per_person_W': None}
                  for zone in self.domain['thermal_zones']}
        occupancy = life.get('occupancy_weekly', {}).get(str(day % 7), life['occupancy'])
        if day >= 7 and 'occupancy_recovery_weekly' in life:
            occupancy = life['occupancy_recovery_weekly'][str(day % 7)]
        for row in occupancy:
            # Weekly life input keeps exact source-minute boundaries. The
            # native People input is the interval mean,not a shifted clock or
            # an invented fractional resident. Legacy daily inputs retain
            # their already grid-aligned semantics.
            fraction = (max(0, min(minute + self.step_min, row['end_min']) -
                                max(minute, row['start_min'])) / self.step_min
                        if 'occupancy_weekly' in life else int(self.within(minute, row)))
            if fraction:
                target = people[row['room_id']]
                target['persons'] += row['persons'] * fraction
                target['activity_total_W'] += row['persons'] * row['activity_W'] * fraction
        for row in people.values():
            if row['persons']:
                row['activity_per_person_W'] = row['activity_total_W'] / row['persons']
        draws = life.get('mixed_water_overrides', {}).get(date, life['mixed_water_daily'])
        active = [row for row in draws if row['start_min'] <= minute < row['start_min'] + row['duration_min'] and row['liters'] > 0]
        flow = sum(row['liters'] / row['duration_min'] for row in active)
        targets = {row['target_C'] for row in active}
        require(len(targets) <= 1, 'CASE_COMMAND_MIXED_TARGETS')
        starts = {**control['program_starts_daily'], **control.get('program_start_overrides', {}).get(date, {})}
        tasks = [{'device': device, 'date': date, 'start_min': minute,
                  'elapsed_start_min': elapsed,
                  'duration_min': self.domain['programs'][device]['duration_min'],
                  'model_key': self.domain['programs'][device]['model_key'],
                  'version': self.domain['programs'][device]['version']}
                 for device in PROGRAMS if minute in starts[device]]
        windows = control.get('ev_window_overrides', {}).get(date, control['ev_daily_windows'])
        ev = life['ev_daily']
        from .eb_water_heater_window import available
        values['water_heater_window_open']=available(self.case,date,minute)
        return {'schema': 'national_idf.case_command_frame.v1', 'frame_index': index,
            'date': date, 'day_index': day, 'start_min': minute, 'elapsed_start_min': elapsed,
            'duration_min': self.step_min, 'control': values, 'people': people,
            'mixed_water': {'flow_L_min': flow, 'target_C': next(iter(targets)) if targets else None,
                            'requested_volume_L': flow * self.step_min},
            'program_starts': tasks,
            'ev': {'connected': any(self.within(minute, row) for row in life['ev_connection_daily']),
                   'charge_window_open': any(self.within(minute, row) for row in windows),
                   'departure_now': minute == ev['departure_min'],
                   'required_departure_SOC': ev['required_departure_SOC'],
                   'traction_kWh': ev['traction_kWh']},
            'formal_admitted': False, 'appliance_service_success_inferred': False}


    def frame(self,index):
        if not self._dated_views:return self._legacy_frame(index)
        elapsed=index*self.step_min;date=(self.begin+dt.timedelta(days=elapsed//1440)).isoformat()
        source=self.case
        try:
            self.case=self._dated_views[date];frame=self._legacy_frame(index)
        finally:self.case=source
        daily=source['life']['by_date'][date];minute=frame['start_min'];length=frame['duration_min']
        amounts=[]
        for draw in daily['mixed_water']:
            overlap=max(0,min(minute+length,draw['start_min']+draw['duration_min'])-max(minute,draw['start_min']))
            if overlap and draw['liters']>0:amounts.append((draw['liters']/draw['duration_min']*overlap,draw['target_C']))
        targets={t for v,t in amounts};require(len(targets)<=1,'CASE_COMMAND_MIXED_TARGETS')
        volume=sum(v for v,t in amounts);frame['mixed_water']=dict(flow_L_min=volume/length,target_C=next(iter(targets)) if targets else None,requested_volume_L=volume)
        trip=daily['ev_trip'];frame['ev'].update(departure_now=trip is not None and minute<=trip['departure_min']<minute+length,required_departure_SOC=trip['required_departure_SOC'] if trip else 0,traction_kWh=trip['traction_kWh'] if trip else 0,departure_min=trip['departure_min'] if trip else None)
        frame['ev']['connected']=any(r['start_min']<=minute and minute+length<=r['end_min'] for r in daily['ev_connections'])
        return frame


class CommandClock:
    """Reject duplicate or skipped begin-zone callbacks before mutating EB state."""
    def __init__(self, timeline):
        self.timeline = timeline
        self.next_index = 0
        self.diagnostics = {'system_clock_differs_from_zone_clock_frames': 0,
                            'first_difference': None}

    def take_exchange(self, exchange, state):
        """Use zone counters, since current_time() can expose the HVAC clock.

        Official 25.2 api/datatransfer.cc currentTime() substitutes the system
        elapsed time when HVAC substeps are shorter than the zone timestep.
        hour()/zone_time_step_number() still identify the zone callback.
        """
        hour = exchange.hour(state)
        number = exchange.zone_time_step_number(state)
        count = exchange.num_time_steps_in_hour(state)
        require(type(hour) is int and 0 <= hour <= 23 and type(count) is int
                and count * self.timeline.step_min == 60 and type(number) is int
                and 1 <= number <= count, 'CASE_COMMAND_ZONE_CLOCK_COUNTERS')
        end_hour = hour + number / count
        system_hour = exchange.current_time(state)
        if abs(system_hour-end_hour)*60 > 1e-7:
            self.diagnostics['system_clock_differs_from_zone_clock_frames'] += 1
            if self.diagnostics['first_difference'] is None:
                self.diagnostics['first_difference'] = {
                    'frame_index': self.next_index, 'zone_end_hour': end_hour,
                    'API_current_time_hour': system_hour, 'hour': hour,
                    'zone_step_number': number, 'steps_in_hour': count}
        return self.take(exchange.month(state), exchange.day_of_month(state), end_hour)

    def take(self, month, day, end_hour):
        frame = self.timeline.frame(self.next_index)
        date = dt.date.fromisoformat(frame['date'])
        require((month, day) == (date.month, date.day)
                and abs(end_hour * 60 - frame['start_min'] - frame['duration_min']) < 1e-7,
                'CASE_COMMAND_CALLBACK_CLOCK', self.next_index)
        self.next_index += 1
        return frame


class EVEbCommands:
    """Apply only explicit EV inputs to the existing EB physical-accounting core.

    Caller supplies the complete frozen hardware/reserve configuration. Target,
    plug and trip inputs never alter hardware. Charging targets and departure
    service targets are reported separately; no arrival SOC reset is performed.
    """
    def __init__(self, ev_class, hardware_and_reserve, timeline):
        required = {'present', 'capacity_kwh', 'charger_kw', 'efficiency', 'min_soc'}
        require(set(hardware_and_reserve) == required and hardware_and_reserve['present'] is True,
                'CASE_EV_FIXED_PARAMETERS_INCOMPLETE')
        life, controls = timeline.case['life'], timeline.case['controls']
        trip = life['ev_daily']
        self.vehicle = ev_class({**hardware_and_reserve, 'initial_soc': life['ev_initial_SOC'],
            'target_soc': controls['ev_target_SOC'], 'arrival_h': trip['return_min'] / 60,
            'departure_h': trip['departure_min'] / 60, 'daily_drive_kwh': trip['traction_kWh']},
            timeline.days, explicit_only=True)
        self.vehicle.enable_physical_accounting()
        self.timeline = timeline
        self.next_index = 0
        self.departure_services = []

    def step(self, frame):
        require(frame == self.timeline.frame(self.next_index), 'CASE_EV_FRAME_ORDER_OR_CONTENT')
        vehicle = self.vehicle
        vehicle.connected = frame['ev']['connected']
        vehicle.target_soc = frame['control']['ev_target_SOC']
        # The original EB core accepts one window per day. Re-evaluate its
        # gate each zone step so disjoint explicit windows remain disjoint.
        vehicle.set_charge_window(frame['day_index'], 0, 24 if frame['ev']['charge_window_open'] else 0)
        if self.timeline.case.get('schema')=='national_idf.case.v3':
            vehicle.daily_drive_kwh=frame['ev']['traction_kWh']
            vehicle.departure_h=(frame['start_min']/60 if frame['ev']['departure_now'] else 25.0)
        before = vehicle._soc
        power = vehicle.step(frame['elapsed_start_min'] / 60, frame['duration_min'] / 60, False)
        if frame['ev']['departure_now']:
            observation = vehicle.departure_observations[frame['day_index']]
            self.departure_services.append({'date': frame['date'], 'SOC_before_departure': before,
                'required_departure_SOC': frame['ev']['required_departure_SOC'],
                'departure_SOC_requirement_met': before >= frame['ev']['required_departure_SOC'] - 1e-12,
                'charging_control_target_SOC': vehicle.target_soc,
                'legacy_EB_charge_target_reached': observation['target_reached'],
                'trip_executed': observation['trip_executed'],
                'missing_traction_kWh': observation['missing_traction_kwh']})
        self.next_index += 1
        return power

    def report(self):
        return {'schema': 'national_idf.case_EV_command_execution.v1',
            'input_sha256': self.timeline.input_sha256, 'executed_steps': self.next_index,
            'expected_steps': self.timeline.steps, 'complete': self.next_index == self.timeline.steps,
            'EB_ledger': self.vehicle.energy_ledger(), 'departure_service': copy.deepcopy(self.departure_services),
            'arrival_SOC_reset': False, 'new_hardware_or_efficiency_inferred': False,
            'formal_admitted': False, 'whole_CASE_executed': False}
