"""Static, identity-checked statistics for a frozen household/A-B batch.

Only GENERATION_STATISTICS.json and GENERATION_STATISTICS.md are intended for public release.
GROUPS.jsonl contains private household identities; it stays with licensed inputs.
No solver, simulator, model API or answer database is imported.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from itertools import zip_longest
from statistics import median
from pathlib import Path

from .common import digest

FUNCTIONS = {"ac": "AC", "washer": "WM", "dryer": "DR",
             "dishwasher": "DW", "water_heater": "WH", "ev": "EV"}
CORE_FIELDS = ("calendar.weekly_events", "comfort", "dwelling.reference_area_m2",
               "equipment.space_ac_available.present")
SCHEMA = "eb.generation_method_statistics.v1"


def read(path):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("PATH_OUTSIDE_BATCH")
    return path


def grouping(cases):
    """Connected components over source household and explicit C/D pair keys."""
    if len({c["case_id"] for c in cases}) != len(cases) or not cases:
        raise ValueError("EMPTY_OR_DUPLICATE_HOUSEHOLD_ID")
    parent = {c["case_id"]: c["case_id"] for c in cases}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        a, b = find(a), find(b)
        parent[max(a, b)] = min(a, b)

    seen = {}
    cd = defaultdict(list)
    for case in sorted(cases, key=lambda c: c["case_id"]):
        cid = case["case_id"]
        source = case["source"]
        source_key = ("source", str(source["dataset"]), str(source["household_key"]))
        keys = [source_key]
        if case.get("cd_pair_id"):
            keys.append(("cd", str(case["cd_pair_id"])))
            cd[str(case["cd_pair_id"])].append(case)
        for key in keys:
            if key in seen:
                union(cid, seen[key])
            else:
                seen[key] = cid
    for rows in cd.values():
        roles = {r["household"]["role_id"].split("_")[1].upper() for r in rows}
        if (len(rows) != 2 or roles != {"C", "D"} or
                len({r["household"]["country"] for r in rows}) != 1):
            raise ValueError("INVALID_CD_CONSTRUCTION_GROUP")
    components = defaultdict(list)
    for case in cases:
        components[find(case["case_id"])].append(case["case_id"])
    group_ids = {root: digest(["construction_group", sorted(ids)])
                 for root, ids in components.items()}
    records = [dict(case_id=c["case_id"],
                    source_group=digest(["source", str(c["source"]["dataset"]),
                                         str(c["source"]["household_key"])]),
                    construction_group=group_ids[find(c["case_id"])])
               for c in sorted(cases, key=lambda c: c["case_id"])]
    return records, len(cd)


def verify_split(groups, assignments):
    if set(assignments) != {g["case_id"] for g in groups}:
        raise ValueError("SPLIT_HOUSEHOLD_SET_MISMATCH")
    seen = {}
    for row in groups:
        split = assignments[row["case_id"]]
        if not isinstance(split, str) or not split:
            raise ValueError("INVALID_SPLIT_NAME")
        for key in ("source_group", "construction_group"):
            token = (key, row[key])
            if token in seen and seen[token] != split:
                raise ValueError("ASSOCIATED_HOUSEHOLDS_CROSS_SPLITS")
            seen[token] = split


def count_map(values):
    return dict(sorted(Counter(values).items()))


def size_summary(values):
    values = sorted(values)
    if not values:
        return dict(count=0, minimum=None, median=None, p90=None, maximum=None)
    return dict(count=len(values), minimum=values[0],
                median=median(values),
                p90=values[math.ceil(len(values)*.9)-1], maximum=values[-1])


def summarize(cases, indexes, pairs, ledger, *, questions_per_household=10):
    groups, cd_pairs = grouping(cases)
    by_id = {c["case_id"]: c for c in cases}
    slots = {(r["case_id"], r["date"]) for r in indexes}
    if len(slots) != len(indexes):
        raise ValueError("DUPLICATE_HOUSEHOLD_DATE")
    counts = Counter(r["case_id"] for r in indexes)
    if set(counts) != set(by_id) or any(v != questions_per_household for v in counts.values()):
        raise ValueError("HOUSEHOLD_QUESTION_QUOTA_MISMATCH")
    root_counts, root_countries = Counter(), defaultdict(set)
    changed = defaultdict(set)
    compositions, mechanism_counts = Counter(), Counter()
    program_shifts = defaultdict(Counter)
    event_counts, event_strata = Counter(), defaultdict(Counter)
    role_country = defaultdict(Counter)
    function_enrollment = defaultdict(Counter)
    control_masks = defaultdict(Counter)
    source_status = {}
    nominal = Counter()
    pair_ids = set()
    for case in cases:
        h = case["household"]
        country, role = h["country"], h["role_id"]
        role_country[country][role] += 1
        stratum = country+"|"+role
        function_enrollment[stratum].update(h["controlled_function_ids"])
        control_masks[stratum]["+".join(sorted(h["controlled_function_ids"]))] += 1
        source_status.setdefault(country, {f: Counter() for f in CORE_FIELDS})
        for field in CORE_FIELDS:
            source_status[country][field][case.get("household_provenance", {}).get(
                field, {}).get("status", "MISSING")] += 1
    for index, pair in zip_longest(indexes, pairs):
        if index is None or pair is None:
            raise ValueError("PAIR_COUNT_MISMATCH")
        cid = index["case_id"]
        case = by_id[cid]
        country, role = case["household"]["country"], case["household"]["role_id"]
        if pair["source_household_sha256"] != digest(case):
            raise ValueError("PAIR_HOUSEHOLD_IDENTITY_MISMATCH")
        for arm in ("A", "B"):
            if digest(pair[arm]) != index[arm+"_sha256"]:
                raise ValueError("PLAN_INDEX_IDENTITY_MISMATCH")
        for key in ("date", "pair_id", "event", "scenario_sha256", "context_sha256",
                    "task_context_sha256"):
            if pair[key] != index[key]:
                raise ValueError("PAIR_INDEX_IDENTITY_MISMATCH:"+key)
        if pair["pair_id"] in pair_ids:
            raise ValueError("DUPLICATE_PAIR_ID")
        pair_ids.add(pair["pair_id"])
        proposal = pair["selected_proposal"]
        if proposal["household_id"] != cid or proposal["date"] != index["date"]:
            raise ValueError("SELECTED_PROPOSAL_IDENTITY_MISMATCH")
        cells = proposal["raw_root_cells"]
        if len(set(cells)) != len(cells):
            raise ValueError("DUPLICATE_ROOT_CELL")
        for cell in cells:
            family, descriptor = json.loads(cell)
            if family not in FUNCTIONS or not isinstance(descriptor, str):
                raise ValueError("INVALID_ROOT_CELL")
            root_counts[(role, cell)] += 1
            root_countries[(role, cell)].add(country)
        families = {r["family"] for r in proposal["components"]}
        functions = {FUNCTIONS[f] for f in families}
        if not functions <= set(case["household"]["controlled_function_ids"]):
            raise ValueError("UNCONTROLLED_FUNCTION_CHANGED")
        changed[cid].update(functions)
        compositions["+".join(sorted(functions))] += 1
        mechanism_counts.update(set(r["mechanism"] for r in proposal["components"]))
        for before in pair["A"]["tasks"]:
            if before["kind"] not in ("washer", "dryer", "dishwasher"):
                continue
            after = next(t for t in pair["B"]["tasks"] if t["task_id"] == before["task_id"])
            delta = after["start_min"] - before["start_min"]
            direction = "earlier" if delta < 0 else "later" if delta > 0 else "unchanged"
            program_shifts[before["kind"]][direction] += 1
        event = json.dumps([index["event"]["start_min"], index["event"]["end_min"]],
                           separators=(",", ":"))
        event_counts[event] += 1
        event_strata[country+"|"+role][event] += 1
        value = proposal.get("nominal_whole_plan_event_reduction_kWh")
        if proposal.get("unknown_thermal_response") or value is None:
            nominal["unknown_thermal_or_missing"] += 1
        elif not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("INVALID_NOMINAL_LOAD_CHANGE")
        else:
            nominal["negative" if value < -1e-9 else "positive" if value > 1e-9 else "zero"] += 1
    declared = {}
    for role, rows in ledger.items():
        for row in rows:
            key = (role, row["key"])
            if key in declared:
                raise ValueError("DUPLICATE_DECLARED_ROOT_CELL")
            declared[key] = row
            if set(row["selected_countries"]) != root_countries.get(key, set()):
                raise ValueError("LEDGER_SELECTED_COUNTRY_MISMATCH")
    if not set(root_counts) <= set(declared):
        raise ValueError("SELECTED_ROOT_OUTSIDE_DECLARED_DOMAIN")
    by_role_function = defaultdict(Counter)
    for (role, cell), row in declared.items():
        family = json.loads(cell)[0]
        key = role+"|"+FUNCTIONS[family]
        by_role_function[key]["declared"] += 1
        if (role, cell) in root_counts:
            by_role_function[key]["selected"] += 1
        if len(root_countries.get((role, cell), set())) >= 2:
            by_role_function[key]["selected_in_at_least_two_countries"] += 1
    missing = Counter()
    for case in cases:
        for fun in set(case["household"]["controlled_function_ids"]) - changed[case["case_id"]]:
            missing[fun] += 1
    sizes = Counter(r["construction_group"] for r in groups)
    summary = dict(
        schema=SCHEMA,
        scope="frozen reference scenarios;static input statistics;not physical or human validation",
        household_count=len(cases), pair_count=len(indexes),
        questions_per_household=questions_per_household,
        countries=count_map(c["household"]["country"] for c in cases),
        roles=count_map(c["household"]["role_id"] for c in cases),
        country_role_counts={k: dict(sorted(v.items())) for k, v in sorted(role_country.items())},
        country_role_cells=sum(len(v) for v in role_country.values()),
        control_function_enrollment={k:dict(sorted(v.items())) for k,v in sorted(function_enrollment.items())},
        control_mask_counts={k:dict(sorted(v.items())) for k,v in sorted(control_masks.items())},
        controlled_function_counts=count_map(str(len(c["household"]["controlled_function_ids"])) for c in cases),
        ac_controlled_households=sum("AC" in c["household"]["controlled_function_ids"] for c in cases),
        key_field_origins={co: {f: dict(sorted(v.items())) for f, v in sorted(fields.items())}
                           for co, fields in sorted(source_status.items())},
        root_coverage=dict(
            declared_cells=len(declared), selected_cells=len(root_counts),
            selected_in_at_least_two_countries=sum(len(v)>=2 for v in root_countries.values()),
            selected_in_one_country=sum(len(v)==1 for v in root_countries.values()),
            selected_question_occurrences=size_summary(root_counts.values()),
            role_function_counts={k:dict(sorted(v.items())) for k,v in sorted(by_role_function.items())},
            definition="role x family x root mechanism/direction/separate-dose descriptor;per-question presence",
            higher_order_or_continuous_coverage_claim=False),
        controlled_household_functions=sum(len(c["household"]["controlled_function_ids"]) for c in cases),
        selected_changed_household_functions=sum(len(v) for v in changed.values()),
        unselected_household_functions=dict(sorted(missing.items())),
        unselected_function_semantics="counts only;no-opportunity status requires separate frozen-domain proof",
        changed_function_compositions=dict(sorted(compositions.items())),
        mechanism_question_counts=dict(sorted(mechanism_counts.items())),
        programme_start_shift_counts={k:dict(sorted(v.items())) for k,v in sorted(program_shifts.items())},
        event_counts=dict(sorted(event_counts.items())),
        country_role_event_counts={k:dict(sorted(v.items())) for k,v in sorted(event_strata.items())},
        nominal_event_change_sign_when_complete=dict(sorted(nominal.items())),
        nominal_event_change_semantics="analytic stated-load change only;unknown thermal is not zero or measured energy",
        groups=dict(
            source_household_groups=len({r["source_group"] for r in groups}),
            construction_groups=len(sizes), cd_pairs=cd_pairs,
            construction_group_household_sizes=count_map(str(v) for v in sizes.values()),
            existing_group_question_sizes=count_map(str(v*questions_per_household) for v in sizes.values()),
            assigned_train_validation_test=False,
            participant_linkage="no responses yet;merge by repeated-participant links before final evaluation splitting",
            construction_groups_are_proven_independent_samples=False))
    return summary, groups


def markdown(s):
    lines = ["# 家庭与A/B聚合统计", "",
             "本页由静态命令从冻结家庭、实际选中计划及覆盖台账重新计算；不运行仿真。", "",
             "| 指标 | 数量 |", "|---|---:|",
             f"| 家庭 / 配对题 | {s['household_count']} / {s['pair_count']} |",
             f"| 源户组 / 构造组 | {s['groups']['source_household_groups']} / {s['groups']['construction_groups']} |",
             f"| C/D配对组 | {s['groups']['cd_pairs']} |",
             f"| 声明 / 已选根动作格 | {s['root_coverage']['declared_cells']} / {s['root_coverage']['selected_cells']} |",
             f"| 至少两国 / 单国根动作格 | {s['root_coverage']['selected_in_at_least_two_countries']} / {s['root_coverage']['selected_in_one_country']} |",
             f"| 受控家庭×功能 / 已选变化 | {s['controlled_household_functions']} / {s['selected_changed_household_functions']} |",
             f"| 每根格题数：最小 / 中位数 / P90 / 最大 | {s['root_coverage']['selected_question_occurrences']['minimum']} / {s['root_coverage']['selected_question_occurrences']['median']} / {s['root_coverage']['selected_question_occurrences']['p90']} / {s['root_coverage']['selected_question_occurrences']['maximum']} |",
             "", "覆盖出现不代表频数均衡或足够统计功效；以下控制组合与事件均为实验配置。",
             "", "## 国家与角色", "", "| 国家 | A | B | C | D | E | F | 合计 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for co, vals in s["country_role_counts"].items():
        by_letter = {r.split("_")[1].upper():n for r,n in vals.items()}
        lines.append("| "+co+" | "+" | ".join(str(by_letter.get(r,0)) for r in "ABCDEF")+f" | {sum(vals.values())} |")
    lines += ["", "## 核心字段来源", "",
              "每项按家庭计数，避免把成员数不同造成的字段数量误当成补全比例。", "",
              "| 国家 | 精确周日程 | 舒适参数 | 参考面积 | 空调存在状态 |", "|---|---|---|---|---|"]
    for co, fields in s["key_field_origins"].items():
        fmt = lambda v: ", ".join(f"{k}: {n}" for k,n in v.items())
        lines.append("| "+co+" | "+" | ".join(fmt(fields[f]) for f in CORE_FIELDS)+" |")
    lines += ["", "## 根动作覆盖的定义", "",
              "一个格由角色、功能、根动作机制、方向和分离的幅度轴构成；仅统计直接事件请求。启动时移/许可时长按0、(0,30]、(30,60]、(60,120]、>120分钟报告；温度差与事件前/中准备轴分开，不把不同轴合成居民负担等级。",
              "", "格定义见[record_raw_cells](../benchmark/ab_generation/generate_native.py)及[动作轴规则](../benchmark/ab_generation/unified/ACTION_AXIS_RULES.json)。939是当前候选域中有见证的根动作格，不是全部连续动作或全部二元/高阶交互组合。",
              "", "| 角色 | AC | WM | DR | DW | WH | EV |", "|---|---|---|---|---|---|---|",
              "| 记法 | 已选/声明（至少两国） | 同左 | 同左 | 同左 | 同左 | 同左 |"]
    for role in sorted(s["roles"]):
        cells=[]
        for fun in ("AC","WM","DR","DW","WH","EV"):
            row=s["root_coverage"]["role_function_counts"].get(role+"|"+fun,{})
            cells.append(f"{row.get('selected',0)}/{row.get('declared',0)} ({row.get('selected_in_at_least_two_countries',0)})")
        lines.append("| "+role.split("_")[1].upper()+" | "+" | ".join(cells)+" |")
    lines += ["", "## 事件分布", "", "| 起止分钟 | 题数 |", "|---|---:|"]
    for e,n in s["event_counts"].items():
        lines.append(f"| {e} | {n} |")
    lines += ["", "## 计划变化", "", "| 改变的功能组合 | 题数 |", "|---|---:|"]
    for k,n in s["changed_function_compositions"].items():
        lines.append(f"| {k} | {n} |")
    lines += ["", "## 分组与解释", "",
              "原生程序变化仍保持完整任务；下表组合计数只说明选中候选改变哪些功能，不代表人类偏好类别或物理收益。",
              "", "同一源户、同一家庭全部题目及C/D配对放入同一构造组。当前未分配训练/验证/测试集；有答卷后还需处理重复参与者关联。875等构造组计数不证明统计独立。",
              "", "未入选的家庭×功能计数："+json.dumps(s["unselected_household_functions"],ensure_ascii=False)+"。这些数量本身不证明无机会，须结合独立的冻结域证明。",
              "", "根动作格是有限离散子域覆盖；完整组合、连续参数、自然性和真人偏好有效性另行评估。名义用电变化不是仿真结果，未知热响应不记作零。",
              "", "完整的分层频数、时移方向、来源状态和输入指纹见[机器可读统计](GENERATION_STATISTICS.json)。"]
    return "\n".join(lines)+"\n"


def frozen_pairs(batch, indexes, household_sha):
    for row in indexes:
        path = relative_file(batch, row["relative_path"])
        if sha(path) != row["pair_file_sha256"]:
            raise ValueError("PAIR_FILE_CHANGED")
        pair = read(path)
        if pair.get("source_manifest_sha256") != household_sha:
            raise ValueError("HOUSEHOLD_FILE_IDENTITY_MISMATCH")
        yield pair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--households", required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--questions-per-household", type=int, default=10)
    parser.add_argument("--split-assignment", help="Optional private JSON map case_id -> split")
    args = parser.parse_args()
    out, batch = Path(args.out), Path(args.batch)
    if out.exists():
        raise FileExistsError(out)
    cases = [json.loads(l) for l in Path(args.households).read_text().splitlines() if l.strip()]
    indexes = [json.loads(l) for l in (batch/"PAIR_INDEX.jsonl").read_text().splitlines() if l.strip()]
    ledger_path = batch/"COHORT_COVERAGE_LEDGER.json.gz"
    summary, groups = summarize(cases, indexes, frozen_pairs(batch, indexes, sha(args.households)), read(ledger_path),
                                questions_per_household=args.questions_per_household)
    summary["input_sha256"] = {"households":sha(args.households),
                               "pair_index":sha(batch/"PAIR_INDEX.jsonl"),
                               "coverage_ledger":sha(ledger_path)}
    summary["statistics_implementation_sha256"] = sha(__file__)
    if args.split_assignment:
        verify_split(groups, read(args.split_assignment))
    out.mkdir(parents=True, mode=0o700)
    (out/"GENERATION_STATISTICS.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    (out/"GENERATION_STATISTICS.md").write_text(markdown(summary))
    (out/"GROUPS.jsonl").write_text("".join(json.dumps(g,sort_keys=True)+"\n" for g in groups))
    print(json.dumps({"households":len(cases),"pairs":len(indexes),
                      "root_cells":summary["root_coverage"]["selected_cells"],
                      "construction_groups":summary["groups"]["construction_groups"],
                      "private_file":"GROUPS.jsonl","simulations":0}))


if __name__ == "__main__":
    main()
