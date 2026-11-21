import base64,hmac,html,os,secrets
from pathlib import Path
from urllib.parse import parse_qs
import yaml
from fastapi import Request
from fastapi.responses import HTMLResponse,RedirectResponse
from .config import Config
from .main import app
C=Path(os.getenv('CONFIG_PATH','/etc/pylon/config.yaml'));E=Path('/etc/pylon/pylon.env');P=Path('/etc/pylon/admin-password')
def pw():
 if not P.exists():P.write_text(secrets.token_urlsafe(24));P.chmod(0o600)
 return P.read_text().strip()
def ok(r):
 try:u,p=base64.b64decode(r.headers.get('authorization','')[6:]).decode().split(':',1)
 except:return False
 return hmac.compare_digest(u,'admin') and hmac.compare_digest(p,pw())
def page(msg=''):
 c=html.escape(C.read_text());return f'<h1>Pylon setup</h1><p>{html.escape(msg)}</p><form method=post><textarea name=config rows=28 cols=90>{c}</textarea><p>Plane API key <input type=password name=PLANE_API_KEY></p><p>GitHub secret <input type=password name=GITHUB_WEBHOOK_SECRET></p><p>Plane secret <input type=password name=PLANE_WEBHOOK_SECRET></p><p>Forgejo secret <input type=password name=FORGEJO_WEBHOOK_SECRET></p><button>Validate and save</button></form>'
def deny():return HTMLResponse('Login required',401,{'WWW-Authenticate':'Basic realm="Pylon"'})
@app.get('/')
async def root():return RedirectResponse('/pylon/admin',307)
@app.get('/admin')
async def get(r:Request):return HTMLResponse(page(r.query_params.get('saved',''))) if ok(r) else deny()

@app.post('/admin')
async def post(r:Request):
 if not ok(r):return deny()
 f={k:v[-1] for k,v in parse_qs((await r.body()).decode()).items()};raw=yaml.safe_load(f['config']);Config.model_validate(raw)
 env={}
 if E.exists():
  for x in E.read_text().splitlines():
   if '=' in x:env[x.split('=',1)[0]]=x.split('=',1)[1]
 for n in ('PLANE_API_KEY','GITHUB_WEBHOOK_SECRET','PLANE_WEBHOOK_SECRET','FORGEJO_WEBHOOK_SECRET'):
  if f.get(n,'').strip():env[n]=f[n].strip()
 for path,text,mode in ((C,yaml.safe_dump(raw,sort_keys=False),0o640),(E,''.join(f'{k}={v}\n' for k,v in sorted(env.items())),0o600)):
  t=Path(str(path)+'.tmp');t.write_text(text);t.chmod(mode);t.replace(path)
 return RedirectResponse('/pylon/admin?saved=Saved.+Restart+Pylon+to+apply.',303)
