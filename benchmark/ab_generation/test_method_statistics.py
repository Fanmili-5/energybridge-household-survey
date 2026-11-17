"""Integrity and grouping counterexamples for the static method exporter."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import hashlib
import unittest

from .common import digest
from .method_statistics import grouping, verify_split, summarize, relative_file, frozen_pairs


def case(cid, role="A", source=None, pair=None):
    result = dict(case_id=cid, source=dict(dataset="SYNTHETIC",household_key=source or cid),
                  household=dict(country="CN",role_id="role_"+role.lower()+"_test",
                                 controlled_function_ids=["AC","WM","DR","DW"]),
                  household_provenance={})
    if pair:
        result["cd_pair_id"]=pair
    return result


def batch():
    cases = [case("left","C",pair="pair"),case("right","D",pair="pair")]
    indexes, pairs, ledger = [], [], {}
    cell = json.dumps(["washer",json.dumps(["start_time_shift","later"])])
    for c in cases:
        role=c["household"]["role_id"]
        a=dict(tasks=[dict(task_id="t",kind="washer",start_min=600)],controls=[],operations=[])
        b=dict(tasks=[dict(task_id="t",kind="washer",start_min=660)],controls=[],operations=[])
        common=dict(date="2007-07-18",pair_id=c["case_id"],event=dict(start_min=1080,end_min=1140),
                    scenario_sha256="scenario",context_sha256="context",task_context_sha256="task")
        p=dict(**common,A=a,B=b,source_household_sha256=digest(c),
               selected_proposal=dict(household_id=c["case_id"],date=common["date"],raw_root_cells=[cell],
                    components=[dict(family="washer",mechanism="start_time_shift")],
                    unknown_thermal_response=True,nominal_whole_plan_event_reduction_kWh=0))
        indexes.append(dict(**common,case_id=c["case_id"],A_sha256=digest(a),B_sha256=digest(b)))
        pairs.append(p)
        ledger[role]=[dict(key=cell,selected_countries=["CN"])]
    return cases,indexes,pairs,ledger


class StatisticsTests(unittest.TestCase):
    def test_cd_pair_and_ten_question_unit_are_not_independent_households(self):
        c,i,p,l=batch()
        s,g=summarize(c,i,p,l,questions_per_household=1)
        self.assertEqual(s["groups"]["construction_groups"],1)
        self.assertEqual(s["root_coverage"]["selected_in_one_country"],2)
        self.assertEqual(s["nominal_event_change_sign_when_complete"],{"unknown_thermal_or_missing":2})
        self.assertNotIn("left",json.dumps(s))

    def test_source_reuse_is_grouped_even_without_cd_marker(self):
        g,n=grouping([case("a",source="shared"),case("b",source="shared")])
        self.assertEqual(g[0]["construction_group"],g[1]["construction_group"])

    def test_cd_split_leakage_fails(self):
        g,n=grouping([case("a","C",pair="p"),case("b","D",pair="p")])
        with self.assertRaisesRegex(ValueError,"CROSS_SPLITS"):
            verify_split(g,{"a":"train","b":"test"})

    def test_missing_split_member_fails(self):
        g,n=grouping([case("a")])
        with self.assertRaisesRegex(ValueError,"SET_MISMATCH"):
            verify_split(g,{})

    def test_invalid_cd_pair_fails(self):
        with self.assertRaisesRegex(ValueError,"INVALID_CD"):
            grouping([case("a","C",pair="p"),case("b","E",pair="p")])

    def test_duplicate_household_or_slot_fails(self):
        c,i,p,l=batch()
        with self.assertRaisesRegex(ValueError,"DUPLICATE_HOUSEHOLD"):
            grouping([c[0],c[0]])
        with self.assertRaisesRegex(ValueError,"DUPLICATE_HOUSEHOLD_DATE"):
            summarize(c,i+[i[0]],p+[p[0]],l,questions_per_household=1)

    def test_wrong_source_or_modified_plan_is_rejected(self):
        c,i,p,l=batch();bad=deepcopy(p);bad[0]["source_household_sha256"]="wrong"
        with self.assertRaisesRegex(ValueError,"HOUSEHOLD_IDENTITY"):
            summarize(c,i,bad,l,questions_per_household=1)
        bad=deepcopy(p);bad[0]["B"]["tasks"][0]["start_min"]=700
        with self.assertRaisesRegex(ValueError,"PLAN_INDEX_IDENTITY"):
            summarize(c,i,bad,l,questions_per_household=1)

    def test_stale_country_coverage_ledger_fails(self):
        c,i,p,l=batch();next(iter(l.values()))[0]["selected_countries"]=["US"]
        with self.assertRaisesRegex(ValueError,"LEDGER_SELECTED_COUNTRY"):
            summarize(c,i,p,l,questions_per_household=1)

    def test_event_mismatch_is_rejected(self):
        c,i,p,l=batch();p[0]["event"]=dict(start_min=960,end_min=1020)
        with self.assertRaisesRegex(ValueError,"PAIR_INDEX_IDENTITY"):
            summarize(c,i,p,l,questions_per_household=1)

    def test_output_paths_cannot_escape_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"PATH_OUTSIDE"):
                relative_file(Path(tmp),"../private.json")


class FrozenFileTests(unittest.TestCase):
    def test_file_change_and_whole_household_file_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"pair.json"
            p.write_text(json.dumps({"source_manifest_sha256":"expected"}))
            ix=[dict(relative_path="pair.json",pair_file_sha256=hashlib.sha256(p.read_bytes()).hexdigest())]
            self.assertEqual(len(list(frozen_pairs(tmp,ix,"expected"))),1)
            with self.assertRaisesRegex(ValueError,"HOUSEHOLD_FILE_IDENTITY"):
                list(frozen_pairs(tmp,ix,"other"))
            p.write_text("{}")
            with self.assertRaisesRegex(ValueError,"PAIR_FILE_CHANGED"):
                list(frozen_pairs(tmp,ix,"expected"))

    def test_missing_pair_stream_is_rejected(self):
        c,i,p,l=batch()
        with self.assertRaisesRegex(ValueError,"PAIR_COUNT_MISMATCH"):
            summarize(c,i,iter(p[:1]),l,questions_per_household=1)
