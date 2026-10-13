import subprocess,os,sys,pathlib
root=pathlib.Path(__file__).resolve().parents[1]
scripts=['worlds.py','generate.py','audit_calendar.py','audit_inputs.py','mechanism_controls.py','source_diagnostics.py','compile_inputs.py','audit_idfs.py']
for name in scripts:
 print({'starting':name,'EP_started':0},flush=True)
 proc=subprocess.run([sys.executable,str(root/'code'/name)],cwd=root,env=os.environ)
 if proc.returncode:raise SystemExit(proc.returncode)
print({'static_chain':'complete','EP_started':0},flush=True)

