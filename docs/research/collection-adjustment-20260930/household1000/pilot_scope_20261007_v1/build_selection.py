"""Select eight frozen input cases without running EnergyPlus or using outcomes."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STAGE = ROOT / "joint_static_production_20261007_v16"
seed = json.loads((HERE / "INITIAL_BOUNDARY_SELECTION.json").read_text())
bindings = json.loads((STAGE / "PAIR_BINDINGS10000.json").read_text())
rows = [dict(r, household_id=h["household_id"])
        for h in bindings["households"] for r in h["records"]]
rows.sort(key=lambda r: (r["household_id"], r["round_index"]))
records = seed["records"]
used = {r["household_id"] for i, r in enumerate(records) if i not in (4, 5)}
for index, family in [(4, "hotwater_preheat_shift"), (5, "identity_control")]:
    candidates = [r for r in rows if r["proposal_family"] == family
                  and r["household_id"] not in used]
    if family == "hotwater_preheat_shift":
        candidates = [r for r in candidates if int(r["date"][5:7]) in (1, 2, 12)]
    r = candidates[0]
    hh, round_index = r["household_id"], r["round_index"]
    records[index] = {
        "household_id": hh, "round_index": round_index, "date": r["date"],
        "coverage": [], "proposal_family": family,
        "pair_path": f"{STAGE.name}/{r['pair_path']}",
        "pair_sha256": r["pair_sha256"],
        "A_IDF_path": f"{STAGE.name}/idfs/{hh}/{round_index:02d}_A.idf",
        "B_IDF_path": f"{STAGE.name}/idfs/{hh}/{round_index:02d}_B.idf",
    }
    used.add(hh)
required_families = {"ev_charge_delay", "ac_setpoint", "task_shift",
                     "hotwater_preheat_shift", "task_plus_ac",
                     "identity_control", "no_legal_change"}
covered = set().union(*(set(r["coverage"]) for r in records))
families = {r["proposal_family"] for r in records}
assert set(seed["covered"]) <= covered
assert required_families <= families
assert len({r["household_id"] for r in records}) == len(records) == 8
for r in records:
    pair_file = ROOT / r["pair_path"]
    assert hashlib.sha256(pair_file.read_bytes()).hexdigest() == r["pair_sha256"]
    pair = json.loads(pair_file.read_text())
    assert pair["date"] == r["date"] and pair["round_index"] == r["round_index"]
    assert pair["simulated_consequences"] is None
    r["IDF_sha256"] = {}
    for arm in ("A", "B"):
        f = ROOT / r[f"{arm}_IDF_path"]
        assert f.is_file()
        r["IDF_sha256"][arm] = hashlib.sha256(f.read_bytes()).hexdigest()
seed.update(records=records, covered=sorted(covered), uncovered=[],
            proposal_families_covered=sorted(families),
            uncovered_proposal_families=sorted(required_families - families),
            selection="prespecified boundary coverage plus all seven proposal families; existing frozen dates only; no outcomes used",
            selection_script="pilot_scope_20261007_v1/build_selection.py",
            checks=seed["checks"] + ["identity-control equivalence and no-legal-change handling"])
(HERE / "PILOT_SELECTION.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"households": 8, "paired_cases": 8,
                  "proposal_families": sorted(families), "EP_runs": 0}, ensure_ascii=False))
