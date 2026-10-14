// Export contract test using a browser engineering fixture; no browser control or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const site = path.resolve(process.argv[2]);
const record = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
global.crypto ??= require('node:crypto').webcrypto;
global.EBRespondentInfo = require(path.join(site, 'respondent-info.js'));
global.EBSourceDraft = require(path.join(site, 'source-draft.js'));
const joint = require(path.join(site, 'joint-view.js'));
// Only the export function reads this one tag; UI initialization above ran without a document.
global.document = {getElementById: id => { assert.equal(id,'joint-needs');return {tagName:'SECTION'}; }};
(async () => {
  const audit = record.audit;
  const args = [audit.source_case,audit.semantic_input,audit.source_binding.source_package_sha256];
  const make = (answer,respondent) => joint.exportRecord(...args,answer,audit.presentation.rendered_snapshot,audit.presentation.presented_at,respondent);
  const a = await make({choice:'accept',score:'',comfort_score:'',energy_score:'',vpp_score:'',comment:'engineering fixture'}, {age_years:21,gender:'female'});
  const b = await make({choice:'reject',score:'1.2',comfort_score:'2.3',energy_score:'3.4',vpp_score:'4.5',comment:'paired engineering fixture'}, {age_years:78,gender:'male'});
  assert.deepEqual(a.input,b.input);
  assert.equal(a.audit.presentation.model_input_sha256,b.audit.presentation.model_input_sha256);
  assert.deepEqual(a.audit.source_case,b.audit.source_case);
  assert.deepEqual(a.audit.source_binding,b.audit.source_binding);
  assert.notDeepEqual(a.respondent,b.respondent);
  assert.notDeepEqual(a.test_feedback,b.test_feedback);
  assert.equal(a.test_feedback.score,null);
  assert.equal(b.test_feedback.score,1.2);
  assert(!Object.hasOwn(a.input,'respondent'));
  console.log(JSON.stringify({passed:true,two_export_variants_same_stimulus_and_source:true,respondent_and_answers_outside_stimulus:true,null_and_decimal_scores_preserved:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
