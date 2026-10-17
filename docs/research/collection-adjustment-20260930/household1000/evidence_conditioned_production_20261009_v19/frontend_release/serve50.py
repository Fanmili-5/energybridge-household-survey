"""Fifty household routes around the actual deployed engineering server; no redesign."""
import argparse, collections, html, json, os, re, threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unified_live_server import App, Handler, encoded

class ServerView:
 def __init__(self,server,app):self._server,self.app=server,app
 def __getattr__(self,name):return getattr(self._server,name)

class MultiHandler(Handler):
 def dispatch(self,method):
  original=self.server;path=urlsplit(self.path).path
  if path in ['/household50','/household50/'] and method=='GET':return self.reply(200,original.catalog,mime='text/html; charset=utf-8')
  if path=='/household50/api/health' and method=='GET':return self.reply(200,{'mode':'engineering_only','households':50,'cases':500,'original_frontend':'live joint-b','human_collection_release':False,'training_release':False})
  if path=='/household50/style.css' and method=='GET':return self.reply(200,(original.release/'households'/original.index[0]['household_id']/'style.css').read_bytes(),mime='text/css')
  prefix=path.split('/')[1] if len(path.split('/'))>1 else ''
  if '/'+prefix not in original.routes:return self.reply(404,{'error':'Not found'})
  app=original.app_for('/'+prefix);self.server=ServerView(original,app)
  try:return super().do_GET() if method=='GET' else super().do_POST()
  finally:self.server=original
 def do_GET(self):return self.dispatch('GET')
 def do_POST(self):return self.dispatch('POST')
 def log_message(self,*args):pass

class MultiServer(ThreadingHTTPServer):
 def __init__(self,release,data_root,origin,port=0):
  self.release=Path(release).resolve();self.data_root=Path(data_root).resolve();self.origin=origin
  self.index=json.loads((self.release/'INDEX50.json').read_text())['households'];assert len(self.index)==50
  self.routes={r['route']:r for r in self.index};self.cache=collections.OrderedDict();self.cache_lock=threading.Lock()
  items=''.join(f'<li><a href="{r["route"]}/">第 {i} 户 · {html.escape(r["province"])} · {r["N"]} 人 · {r["G"]} 代 · {r["K"]} 类设备 · 10个日期</a></li>' for i,r in enumerate(self.index,1))
  self.catalog=('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>50户服务器测试 · EnergyBridge</title><link rel="stylesheet" href="/household50/style.css"></head><body class="survey-page"><header><span class="brand">EnergyBridge</span><span>50户服务器测试</span></header><main><section class="panel"><h1>选择测试家庭</h1><p>每户保留原季度随机10天；包含多种提案情境，采用判断由您填写，共500组A/B。沿用原家庭用电安排页面，接入本次服务器实际配对仿真结果。回答保存为工程测试记录。</p><p>这些是城市住宅参考家庭，模型结果尚未完成实测校准；没有预设真人答案。</p><ol>'+items+'</ol></section></main></body></html>').encode()
  super().__init__(('127.0.0.1',port),MultiHandler)
 def app_for(self,route):
  with self.cache_lock:
   if route in self.cache:app=self.cache.pop(route);self.cache[route]=app;return app
   row=self.routes[route];app=App(self.release/'households'/row['household_id'],self.data_root/row['household_id'],route,self.origin)
   self.cache[route]=app
   while len(self.cache)>4:self.cache.popitem(last=False)
   return app

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--release',type=Path,required=True);ap.add_argument('--data-root',type=Path,required=True);ap.add_argument('--public-origin',default='https://47.85.194.154');ap.add_argument('--port',type=int,default=18775);a=ap.parse_args();os.umask(0o077)
 s=MultiServer(a.release,a.data_root,a.public_origin,a.port)
 try:s.serve_forever()
 finally:s.server_close()
