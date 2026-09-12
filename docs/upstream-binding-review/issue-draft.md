# Default family IDFs lack four appliance write-back objects used by family_runner

Draft only; not submitted.

The retrofit report (§10.1) explicitly says the old static household loads and washer/dishwasher DHW branches were removed for the EV/EWH experiment. This report does not dispute that decision or propose restoring those schedules/branches. It concerns the current multi-appliance execution code, whose write-back helper explicitly expects four dynamic ElectricEquipment objects, while the default runtime assets do not provide them.

Follow-up verification used the README's current reproduction path: `run_main_benchmark_from_scratch.sh → run_household_matrix.py → run_multi_user_household.py → family_runner.run_family_agent`. All 50 main jobs were prepared up to the simulator boundary (not simulated with their policies); all five methods received identical prepared IDFs within each household/region group. The daily capacity runner reaches the same multi-user entry.

Through the unmodified multi-user entry, I also completed four no_dr reference simulations: Tianjin/Germany seven-day references plus Tianjin/Germany one-day tasks constructed by the capacity generator. All completed with EP exit code 0 and no model calls. In all four, the four handles below were -1 while ApplianceSuite produced nonzero powers; EV and water-heater handles were valid. This checks actual generated runtime assets, not just default path constants. The seven-day no_dr references are not one of the five main-matrix evaluated methods.

On main `2b17ae63e613da776c93e900f5dace50d63a88a8`, `family_runner._FamilyLoop.init` requests these Schedule:Constant actuators:

- ClothesWasher_Power_Frac
- Dishwasher_Power_Frac
- ClothesDryer_Power_Frac
- Refrigerator_Power_Frac

The default Tianjin 3/7/14-day and Berlin IDFs do not define them or the corresponding ElectricEquipment objects. `_write_appliance_actuators` skips handles equal to -1.

I reproduced this using EnergyPlus 24.1 and the unmodified write-back function extracted from the above commit, with deterministic power inputs and no LLM calls. For each template I used a single July 1 run period and the Tianjin EPW to isolate the binding issue; this is not a Berlin climate or full benchmark validation.

With the original templates, all four handles are -1 and the entire facility-meter trace is identical for zero input versus a one-hour nonzero pulse. In an experimental copy, adding the corresponding schedules/equipment yields nonnegative handles and the expected individual metered energy (1.0, 0.75, 1.5 and 0.1 kWh for a one-hour pulse at 50% of the runner's design levels). Shifting the pulse by two hours shifts the measured appliance load by two hours. A zero-input patched run reproduces the original zero-input facility trace. The v2 PPO environment's separate write-back function also produces the expected individual appliance energies.

Is an IDF-generation step or a different intended asset missing from this checkout? If these objects should be added, should their heat-gain fractions follow `original_model.idf`, including for Berlin? The experimental patch uses that file only as a review candidate, not as evidence of validated thermal parameters.

Additional no-model controls confirm the upstream action application and ApplianceSuite can move washer/dishwasher/dryer tasks from 18–19 to 20–21 and emit the expected powers. Separately, 20 real EP interface runs (two templates, ten conditions each) reproduce the missing write-back and verify existing EV/EWH/HVAC controls respond. An electrical-only diagnostic repair uses zero indoor heat gains to isolate metering, not to propose calibrated thermal parameters. This is not a paid-model planning benchmark or validation of Berlin climate performance.

I would keep a proposed fix at the common asset/binding layer and use it consistently across agent, no_dr and the baseline execution paths. I have not established full MPC/PPO regression or compatibility with existing trained checkpoints, and would not mix pre-fix benchmark scores with post-fix results. This report does not propose changes to planning, acceptance or scoring.
