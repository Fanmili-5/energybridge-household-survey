"""Interface, tamper and unavailable-data regressions; never call an EP engine."""
import copy
import http.client
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from benchmark.ab_generation.common import read, save, seal
from .pipeline import HERE, configuration
from .questionnaire import changes, display_plans, preview_assets, verify_questionnaire
from .server import handler, PREFIX
from http.server import ThreadingHTTPServer


class ProjectTests(unittest.TestCase):
    def test_registered_input_is_exact_and_declared_before_generation(self):
        config, source = configuration(HERE / 'examples/project.json')
        self.assertTrue(source.is_file())
        self.assertEqual(config['preview_plan']['seed'], 20261019)
        self.assertFalse(config['preview_plan']['stress_admissions'])
        self.assertEqual(len(config['preview_plan']['variants'][0]['overrides']['program_shifts_min']), 24)
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'wrong.json'; bad = copy.deepcopy(config)
            bad['family_input']['sha256'] = '0' * 64; save(p, bad)
            with self.assertRaisesRegex(ValueError, 'PROJECT_FAMILY_INPUT_CHANGED'):
                configuration(p)

    def test_schedule_projection_keeps_cross_boundary_service_chain(self):
        task = {'task_id':'w','need_id':'w','asset_id':'washer','kind':'washer','start_min':470,'end_min':530}
        op = {'operation_id':'o','need_id':'w','asset_id':'washer','kind':'load','start_min':450,'end_min':460}
        controls = [{'asset_id':'ac','kind':'ac_setpoint','start_min':-3000,'end_min':5000,'heating_setpoint_C':20,'cooling_setpoint_C':26}]
        a = {'tasks':[task], 'operations':[op], 'controls':controls}
        pair = {'A':a,'B':copy.deepcopy(a)}; original=copy.deepcopy(pair)
        shown = display_plans(pair)
        self.assertEqual(shown['A']['tasks'], [task]); self.assertEqual(shown['A']['operations'], [op])
        self.assertEqual(shown['A']['controls'][0]['start_min'],480)
        self.assertEqual(shown['A']['controls'][0]['end_min'],1920)
        self.assertEqual(changes(shown),[]); self.assertEqual(pair,original)

    def test_control_diff_is_semantic_not_artificial_segmentation(self):
        c = {'asset_id':'ac','kind':'ac_setpoint','start_min':480,'end_min':1920,'heating_setpoint_C':20,'cooling_setpoint_C':26}
        a={'tasks':[],'operations':[],'controls':[c]}
        b={'tasks':[],'operations':[],'controls':[dict(c,end_min=1000),dict(c,start_min=1000)]}
        self.assertEqual(changes({'A':a,'B':b}),[])
        b['controls'][1]['cooling_setpoint_C']=27
        delta=changes({'A':a,'B':b});self.assertEqual(len(delta),1)
        self.assertEqual((delta[0]['start_min'],delta[0]['end_min']),(1000,1920))

    def test_v69_questions_scales_and_css_are_preserved(self):
        source=HERE.parent/'collector'
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); preview_assets(folder)
            html=(folder/'public/index.html').read_text();original=(source/'index.html').read_text()
            self.assertEqual(html.split('<form id="response-form">')[1].split('</form>')[0],
                original.split('<form id="response-form">')[1].split('</form>')[0])
            for name in ['view.css','base.css','required-response.js']:
                self.assertEqual((folder/'public'/name).read_bytes(),(source/name).read_bytes())
            self.assertNotIn('workbench',html)
            subprocess.run(['node','--check',str(folder/'public/view.js')],check=True,capture_output=True)

    def test_pending_results_cannot_elicit_answers(self):
        subprocess.run(['node',str(HERE/'test_preview_client.js')],check=True,capture_output=True)

    def test_concrete_household_materials_explain_commands_without_claiming_results(self):
        root=HERE/'examples/questionnaire'; index=read(root/'public/index.json')
        row=next(r for r in index['cases'] if r['case_id'].endswith('3c33405006eea121bdeb45e0d92f12733fb0805451f9471ae2a271d675e4c943'))
        case=read(root/'public'/row['path']);text=''.join(case['project_presentation']['family_lines'])
        for item in ['36岁男','建筑面积50.0㎡','可用面积42.0㎡','起居兼卧室','室外专用车位',
                     '19:00—19:30 晚餐','次日07:00—次日08:00','次日08:00出发',
                     '充电窗口在次日07:50结束','不是已达到的电量','衣物量1.2 kg']:
            self.assertIn(item,text)
        shown=read(root/'DISPLAY_MODELS.json')[case['case_id']]
        self.assertIn('这是请求目标，实际响应未计算',shown['request'])
        self.assertIn('制冷设定26℃',shown['schedule']);self.assertIn('水箱加热设定55℃',shown['schedule'])
        self.assertIn('允许充电不表示全程充电',shown['schedule'])
        self.assertIn('其他设备沿用A',shown['changes'])
        self.assertLess(shown['changes'].index('装入衣物 18:10'),shown['changes'].index('洗衣运行 18:20'))
        washer=lambda side:[r for r in case['plans'][side]['tasks'] if r['kind']=='washer']
        a,b=washer('A'),washer('B');self.assertEqual(len(a),1);self.assertEqual(len(b),1)
        self.assertEqual(b[0]['start_min']-a[0]['start_min'],40)
        self.assertEqual({k:v for k,v in a[0].items() if k not in ['start_min','end_min']},
                         {k:v for k,v in b[0].items() if k not in ['start_min','end_min']})

    def test_invalid_timer_plan_shows_unchanged_handling_context(self):
        root=HERE/'examples/questionnaire';index=read(root/'public/index.json')
        row=next(r for r in index['cases'] if r['case_id'].endswith('5b0eca5c2828aaf50539511b09452738192d8d1fdf3725e4684d2a08c0c7e9bb'))
        shown=read(root/'DISPLAY_MODELS.json')[row['case_id']]['changes']
        # The invalid B still runs before load. Show both literally rather than
        # hiding unchanged load/unload behind the full-schedule disclosure.
        self.assertIn('装入餐具 20:00–20:10',shown)
        self.assertIn('洗碗机运行 18:30–19:10',shown)
        self.assertIn('取出餐具 20:50–21:00',shown)
        self.assertNotIn('应拒绝',shown)

    def test_generated_family_context_keeps_identity_and_has_no_thermal_trace(self):
        from benchmark.family_generation.core import generate
        from benchmark.family_generation.connect import connect
        from benchmark.ab_generation.common import bound
        from benchmark.ab_generation.generate import generate as generate_B
        from .context import plan_context
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); families=generate(HERE.parent/'family_generation/examples/batch.json',root/'families')
            connected=connect(root/'families',root/'connected')
            for row in connected['records']:
                hid=row['household_id'];source=next(r for r in families['records'] if r['household_id']==hid)
                life_root=root/'connected/life_A'/hid
                life=read(bound(life_root,read(life_root/'MANIFEST.json')['records'][0]['path']))
                world=read(life_root/'WORLD_INPUT.json')['households'][0]
                c=plan_context(life,world,{'case_id':hid+'-test','date':'2025-07-15','events':[], 'tariff':[]},source['sha256'])
                self.assertEqual(c['household_id'],hid)
                self.assertEqual(c['reference']['thermal'],{})
                self.assertEqual({d['asset_id'] for d in c['devices']},set(c['authority']['assets']))
                self.assertEqual(c['source']['family_sha256'],source['sha256'])
                self.assertEqual(c['reference']['information_set']['mode'],'offline_unexecuted_A_plan')
                self.assertTrue(all(r['grid_kWh']>0 for r in c['reference']['ev_charging_steps']))
                result=generate_B(c,{'joint_family_limit':1})
                self.assertFalse(result['final_B_outcomes_used_for_selection'])

    def test_published_materials_all_render_and_tampering_is_rejected(self):
        source=HERE/'examples/questionnaire'
        self.assertTrue(verify_questionnaire(source)['passed'])
        run=subprocess.run(['node',str(HERE/'verify_display.js'),str(source)],check=True,capture_output=True,text=True)
        self.assertIn('"cases":37',run.stdout)
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'copy';shutil.copytree(source,target)
            index=read(target/'public/index.json');case_path=target/'public'/index['cases'][0]['path']
            case=read(case_path);case['VPP_results']=[];save(case_path,case)
            with self.assertRaises(ValueError):verify_questionnaire(target)
            # Even a newly sealed package may not recast unknown outcomes as [].
            from benchmark.ab_generation.common import sha
            index['cases'][0]['sha256']=sha(case_path);save(target/'public/index.json',index)
            seal(target,{'schema':'eb.project.v69_preview.v1','ui_revision':'eb.questionnaire50.collection.v69','new_EP_runs':0})
            with self.assertRaisesRegex(ValueError,'UNCOMPUTED_OUTCOMES'):
                verify_questionnaire(target)

    def test_native_family_relationships_and_shared_home_scope_survive_projection(self):
        root=HERE/'examples/questionnaire';index=read(root/'public/index.json')
        row=next(r for r in index['cases'] if r['household_id']=='project-demo-000003')
        case=read(root/'public'/row['path']);text=''.join(case['project_presentation']['family_lines'])
        self.assertIn('成员1是成员2的伴侣',text)
        self.assertIn('成员1是成员3的家长',text)
        self.assertIn('其他住户',text)
        self.assertIn('未给定个人舒适温度范围',text)
        profile=read(root/'public/households/project-demo-000003.json')
        self.assertEqual(profile['area_scope'],'whole_reference_dwelling;not_household_allocated_area')

    def test_preview_http_has_no_collection_generation_or_simulation_endpoint(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(HERE/'examples/questionnaire'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(method,path):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10);c.request(method,path)
            response=c.getresponse();body=response.read();code=response.status;c.close();return code,body
        try:
            self.assertEqual(request('GET',PREFIX+'/form')[0],200)
            self.assertEqual(request('GET',PREFIX+'/../../SUMMARY.json')[0],404)
            self.assertEqual(request('GET',PREFIX+'/api/state')[0],404)
            for path in ['api/answers','api/build','api/prepare-idf','api/run-simulation']:
                self.assertEqual(request('POST',PREFIX+'/'+path)[0],405)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
