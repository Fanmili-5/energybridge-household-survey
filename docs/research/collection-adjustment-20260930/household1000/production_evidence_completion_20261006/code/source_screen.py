"""Primary-source applicability screening, including disconfirming evidence."""
import hashlib,html,json,re,shutil
from pathlib import Path
from pypdf import PdfReader
OUT=Path(__file__).resolve().parent.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 article=(OUT/'raw/CEEG_article.html').read_text();authors=[html.unescape(s) for s in re.findall(r'<meta name="citation_author" content="([^"]+)"',article)]
 a=json.loads((OUT/'raw/3-1 Household basic information.json').read_text());b=json.loads((OUT/'raw/3-2 Household EEG-related information.json').read_text());meta=json.loads((OUT/'raw/CEEG_article_23514693.json').read_text())
 assert len(a)==len(b)==1327 and {r['Code'] for r in a}=={r['Code'] for r in b}
 for fn in ['3-1 Household basic information.json','3-2 Household EEG-related information.json','4-3 Questionnaire in English and Chinese translations.pdf']:
  items=json.loads((OUT/'raw/CEEG_collection_all_metadata.json').read_text())
  # File-level MD5 has already been checked at acquisition; repeat against
  # corresponding detailed metadata when it is present locally.
  detailed=[]
  for path in (OUT/'raw').glob('CEEG_article_*.json'):
   detailed+=json.loads(path.read_text()).get('files',[])
  m=next(f for f in detailed if f['name']==fn);assert hashlib.md5((OUT/'raw'/fn).read_bytes()).hexdigest()==m['computed_md5']
 title=PdfReader(OUT/'raw/4-3 Questionnaire in English and Chinese translations.pdf').pages[0].extract_text()
 assert 'urban residents in Beijing' in title
 screen={'paper_title':'A dataset on energy efficiency grade of white goods in mainland China at regional and household levels',
  'authors_from_primary_article':authors,'paper_DOI':'10.1038/s41597-023-02358-x','primary_URL':'https://www.nature.com/articles/s41597-023-02358-x',
  'data_collection_DOI':'10.6084/m9.figshare.c.6234957.v1','public_household_records_checked':1327,'household_license':meta['license'],
  'released_household_frame':'Beijing urban residents, explicit questionnaire and ring-road fields',
  'released_household_device_information':'average EEG and household energy-saving attitude/behavior, not individual device inventory',
  'regional_sales_market_share_is_not_installed_household_stock_frequency':True,
  'ordinary_city_H5_probability_sampling_and_reference2020_alignment_not_established':True,
  'national2020_device_prevalence_admission':False,'specific_installed_device_instance_admission':False,
  'concrete_plan_consent_or_load_response_label_admission':False,
  'possible_future_use':'separately labelled Beijing external diagnostic after frame/time selection review;no automatic production replacement',
  'raw_public_pseudonyms_or_attitudes_not_transferred_to_generated_roles':True}
 save('CEEG_SOURCE_SCREEN.json',screen)
 if Path('/private/tmp/eb_window4_p14.png').exists():shutil.copyfile('/private/tmp/eb_window4_p14.png',OUT/'raw/LBNL_WINDOW4_primary_p14.png')
 register=[
 {'source_ID':'NBS_2020','kind':'official aggregate census','URLs':['https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/lefte.htm','https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf'],
  'read':'actual B0901a/B0902a/B0903a/B0904a/B0906a tables and scheme','supports':'city ordinary household denominators and ten stock feature marginal controls','does_not_support':'unknown multivariate joint, physical device models, reference count1000 sufficiency'},
 {'source_ID':'CRECS2012','kind':'primary survey + original research','URLs':['https://crecs.ruc.edu.cn/jj/gyCRECS/index.htm','https://www.sciencedirect.com/science/article/pii/S0301421514004200'],
  'DOI':'10.1016/j.enpol.2014.07.016','publication':'Zheng et al. 2014 Energy Policy75:126-135',
  'read':'local licensed2012 questionnaire, raw metadata and positive slot data;publisher indexed abstract','supports':'historical individual appliance reports and explicit survey year2012','does_not_support':'2020 census-city ordinary ownership prevalence or assigned household installed hardware'},
 {'source_ID':'An2023_DeST','kind':'primary Chinese prototype research','URLs':['https://www.sciopen.com/article/10.1007/s12273-023-1058-5','https://app.dest.net.cn/'],
  'DOI':'10.1007/s12273-023-1058-5','publication':'An, Wu, Gui, Yan2023 Building Simulation16(8):1559-1582',
  'read':'publisher abstract and metadata;original189 used native parameter tables;fullpaper retrieval not completed',
  'supports':'code/reference prototype parameters;151 prototype models extended to9225 models270cities',
  'does_not_support':'native library counts as household weights;native floorplan or exact installed construction recovery'},
 {'source_ID':'Ahfock2016','kind':'primary statistical-matching methodology','URLs':['https://digital.library.adelaide.edu.au/items/c2e5af13-8c5a-4273-b2fd-64f1b0e6d8ed','https://digital.library.adelaide.edu.au/server/api/core/bitstreams/3826e064-edd5-4d60-9778-31a5f8697748/content'],
  'DOI':'10.1016/j.csda.2016.06.005','publication':'Ahfock, Pyne, Lee, McLachlan2016 Computational Statistics & Data Analysis104:79-90',
  'read':'primary archived paper','supports':'unidentified cross-source association must be distinguished from point completion',
  'does_not_support':'their Gaussian/Gibbs algorithms empirically validate our categorical couplings;our Frechet bounds independently derived'},
 {'source_ID':'ResStock2024_1','kind':'national laboratory method documentation','URLs':['https://www.nrel.gov/docs/fy24osti/88109.pdf','https://github.com/NatLabRockies/resstock'],
  'read':'primary indexed Section4 sample-size text and official conditional probability workflow;PDF download failed',
  'supports':'quota-based reference samples, explicit dependencies, archetype generation and sample-size uncertainty review',
  'does_not_support':'US parameters or1000/15percent guideline automatically valid in China'},
 {'source_ID':'LBNL_SC','kind':'primary physical definition','URLs':['https://hes-documentation.lbl.gov/calculation-methodology/calculation-of-energy-consumption/heating-and-cooling-calculation/doe2-inputs-assumptions-and-calculations/the-doe2-model','https://eta-publications.lbl.gov/sites/default/files/33943.pdf'],
  'read':'Home Energy Saver equation2;WINDOW4 primary scannedPDF page14 printed9 visually inspected',
  'supports':'SC-SHGC scalar relation under common parameter boundary;0.86vs0.87 reference-spectrum convention difference',
  'does_not_support':'native frame/glass boundary agreement or angular/spectral equivalence'},
 {'source_ID':'IKEA_sleep','kind':'primary manufacturer geometric data','URLs':['https://www.ikea.com/gb/en/p/tuffing-bunk-bed-frame-dark-grey-00239233/','https://www.ikea.com/nl/en/p/neiden-bed-frame-pine-40395245/'],
  'read':'manufacturer outer frame dimensions, upper berth age exclusion and load limits','supports':'selected reference furniture dimensions',
  'does_not_support':'Chinese ownership frequencies or0.6/0.8m statutory clearance or universal accessibility'},
 {'source_ID':'Miele_cycle','kind':'primary OEM Chinese-language manual','URLs':['https://media.miele.com/downloads/83/d4/01_C7F12828BC641EDEA4EAE0B7FDA083D4.pdf'],
  'read':'manual pages11/81/82 and delay-start/installation context','supports':'selected washing/drying test-energy duration water load and noninterruptible safety constraints',
  'does_not_support':'all source washers are this model;actual clocks/duty/Chinese national appliance distribution'},
 {'source_ID':'Haier_physical','kind':'primary OEM performance or energy label','URLs':['https://www.haier.com/air_conditioners/20130503_99020.shtml','https://www.haier.com/water_heaters/drsq/20210819_167043.shtml','https://file.c.haier.net/obs-cpzx/materialprod/2023/12/21/1737726717934243840/e6dcd3e59b3e573efb4fe2c23fb6ea01.pdf'],
  'read':'primary web specifications;fridge manual pages8/35;three HTML cache downloads403 retained as failed',
  'supports':'specific thermal vs electric rated powers and daily label energy','does_not_support':'offdesign curves, observed source-device identity or2020 household stock ownership'},
 {'source_ID':'CEEG2023','kind':'primary data descriptor and released data','URLs':['https://www.nature.com/articles/s41597-023-02358-x','https://api.figshare.com/v2/collections/6234957/articles?page_size=100'],
  'read':'article + released questionnaire + both1327record schema files +MD5','supports':'scope of a separate Beijing EEG survey','production_admission':'excluded for national individual appliance ownership and plan labels'},
 {'source_ID':'CHEAA2016','kind':'original usability study with secondary specification table','URLs':['https://www.cheaa.org/upload/files/2016/2/4141546561.pdf'],
  'read':'PDFpage71 table1 footnote','production_admission':'excluded as original energy measurement;OEM-only replacement cycle chosen'},
 {'source_ID':'Urban_behavior2024','kind':'primary research lead','URLs':['https://www.sciencedirect.com/science/article/pii/S0378778824010053'],'DOI':'10.1016/j.enbuild.2024.114889',
  'read':'primary indexed title/abstract only;full text403','production_admission':'no usable raw behavioral clock distribution, census-city-only frame or weights admitted'},
 {'source_ID':'ScientificAgentSkills2026','kind':'procedural software workflow reference','URLs':['https://arxiv.org/abs/2609.00065'],
  'publication':'Kassis, Agarwal, He, Patel, Brueckner2026 Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents',
  'supports':'procedural evidence-review skill implementation only','does_not_support':'Chinese population, physical parameter or benchmark validity'}]
 save('SOURCE_REGISTER.json',{'sources':register,'targeted_primary_review_not_systematic_or_exhaustive':True,
  'screening_questions':['population frame and epoch','actual joint observations','units and questionnaire branches','definition vs empirical model validity','identifiable claim vs declared design'],
  'negative_and_failed_retrieval_evidence_retained':True})
 print(json.dumps({'source_entries':len(register),'CEEG_records_screened':1327,'CEEG_national_asset_admitted':False,'CHEAA_original_energy_measurement_admitted':False},ensure_ascii=False))
if __name__=='__main__':main()
