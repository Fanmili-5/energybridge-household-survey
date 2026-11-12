"""The new household entry must not silently use the legacy API protocol."""
import unittest
from unittest.mock import patch
from .candidates import generate_household_day
from .contract import config,entry_config

class HouseholdEntryConfigurationTests(unittest.TestCase):
    def invoke(self,cfg=None):
        bound={'native_execution_contract':{}}
        with patch('benchmark.ab_generation.eb_alignment.verify_native_target',return_value={'verified':True}), \
             patch('benchmark.ab_generation.eb_alignment.bind_household',return_value=bound), \
             patch('benchmark.ab_generation.unified.candidates.generate_day',return_value={'mocked':True}) as generate:
            generate_household_day({}, {}, 'manifest',cfg,native_appliance_source_path='preflight-mocked')
        return generate.call_args.args[1]
    def test_omitted_configuration_uses_current_protocol(self):
        self.assertEqual(entry_config(),self.invoke())
        self.assertEqual('delivery_v2_11',self.invoke()['method_revision'])
    def test_explicit_legacy_replay_configuration_is_preserved(self):
        old=config({'method_revision':'delivery_v2_3'})
        self.assertEqual(old,self.invoke(old))

if __name__=='__main__':unittest.main()
