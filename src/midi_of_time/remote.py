"""MIDI of Time - optional phone remote (home network only, PIN protected, off by default).

The app starts serve(app, port, pin). Requests are handed to the Tk thread through a queue, so the
window and the phone always see the same state.
"""
import json, queue, socket, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#17140f"><title>MIDI of Time</title>
<style>
:root{--bg:#17140f;--panel:#231e16;--ink:#efe3c2;--gold:#d4a72c;--dim:#9c8f73;--green:#5fa35a;--red:#c4553f;--amber:#e0a43a}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--ink);font:16px system-ui,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 6px}
h1{margin:0;color:var(--gold);font:700 22px Georgia,serif}
#st{font-size:13px;display:flex;align-items:center;gap:6px}#dot{width:10px;height:10px;border-radius:50%;background:var(--dim)}
.card{background:var(--panel);margin:8px 12px;border-radius:12px;padding:14px}
#title{font:700 19px Georgia,serif;margin:0 0 4px}#info,#follow{font-size:13px;color:var(--dim)}#follow{color:var(--gold)}
#warn{font-size:13px;color:var(--amber);margin-top:4px}
button{font:inherit;border:0;border-radius:10px;padding:12px;background:#2f281d;color:var(--ink)}
#play{width:100%;background:var(--gold);color:var(--bg);font:700 26px system-ui;padding:18px;margin-top:12px}
#play:disabled{opacity:.45}.row{display:flex;gap:8px;margin-top:8px}.row button{flex:1}
.bar{height:8px;background:#0e0c09;border-radius:4px;margin-top:12px;overflow:hidden}#fill{height:100%;width:0;background:var(--gold)}
#time{font-size:12px;color:var(--dim);text-align:right;margin-top:4px}
.seg{display:flex;gap:6px;margin-top:10px}.seg button{flex:1;font-size:13px;padding:8px}.seg .on{background:var(--gold);color:var(--bg)}
#q{width:100%;padding:12px;border-radius:10px;border:0;background:#0e0c09;color:var(--ink);font:inherit}
.tabs{display:flex;gap:6px;margin:10px 0 6px;overflow-x:auto}.tabs button{padding:8px 12px;font-size:14px;white-space:nowrap}.tabs .on{background:var(--gold);color:var(--bg)}
#list div{padding:12px 6px;border-bottom:1px solid #2f281d;display:flex;align-items:center;gap:8px}#list div.sel{color:var(--gold);font-weight:700}
#list .nm{flex:1}#list .star{background:none;font-size:22px;padding:2px 8px;color:var(--dim)}#list .star.on{color:var(--gold)}
#list small{color:var(--dim);display:block;font-size:12px}
#pin{display:none;text-align:center;padding:40px 20px}#pin input{font-size:28px;width:140px;text-align:center;padding:10px;border-radius:10px;border:0}
</style></head><body>
<div id="pin"><h1>MIDI of Time</h1><p>Enter the PIN shown in the app on your PC.</p><input id="pinin" inputmode="numeric" maxlength="8"><p><button onclick="savePin()">Connect</button></p></div>
<div id="app" style="display:none">
<header><h1>MIDI of Time</h1><div id="st"><span id="stt">…</span><span id="dot"></span></div></header>
<div class="card"><p id="title">Pick a song</p><div id="info"></div><div id="warn"></div>
<div class="seg"><button id="m_smart" onclick="mode('smart')">Smart: follows the tune</button><button id="m_part" onclick="mode('part')">One part</button></div>
<button id="play" onclick="cmd('play')">▶ PLAY</button>
<div class="row"><button id="pause" onclick="cmd('pause')">❚❚ Pause</button><button onclick="cmd('stop')">■ Stop</button><button onclick="cmd('next')">Next ▶▶</button></div>
<div class="bar"><div id="fill"></div></div><div style="display:flex;justify-content:space-between"><span id="follow"></span><span id="time"></span></div>
<div id="msg" style="font-size:13px;margin-top:8px"></div></div>
<div class="card"><input id="q" placeholder="Filter songs, or search your MIDI folder" oninput="render()" onkeydown="if(event.key==='Enter')lib()">
<div class="tabs"><button data-v="all" class="on" onclick="tab('all')">My songs</button><button data-v="fav" onclick="tab('fav')">★ Favorites</button><button data-v="recent" onclick="tab('recent')">Recent</button><button data-v="lib" onclick="lib()">Search MIDI folder</button><button id="sortb" onclick="toggleSort()">Sort: Name</button></div>
<div id="list"></div></div></div>
<script>
let SORT=localStorage.getItem('ocsort')||'name';
function kb(n){return n<1048576?Math.round(n/1024)+' KB':(n/1048576).toFixed(1)+' MB'}
function toggleSort(){SORT=SORT=='size'?'name':'size';localStorage.setItem('ocsort',SORT);render()}
let K=localStorage.getItem('ocpin')||new URLSearchParams(location.search).get('k')||'',songs={},view='all',sel=null,S={};
function savePin(){K=document.getElementById('pinin').value.trim();localStorage.setItem('ocpin',K);start()}
async function api(p,body){const r=await fetch(p+(p.includes('?')?'&':'?')+'k='+encodeURIComponent(K),body?{method:'POST',body:JSON.stringify(body)}:{});
 if(r.status==403){document.getElementById('app').style.display='none';document.getElementById('pin').style.display='block';throw 'pin'}return r.json()}
function fmt(s){s=Math.max(0,s|0);return (s/60|0)+':'+String(s%60).padStart(2,'0')}
async function poll(){try{S=await api('/api/state');const c={green:'#5fa35a',gold:'#d4a72c',amber:'#e0a43a',red:'#c4553f',dim:'#9c8f73'};
 stt.textContent=S.status;dot.style.background=c[S.color]||c.dim;title.textContent=S.title||'Pick a song';info.textContent=S.info||'';warn.textContent=S.warn||'';
 msg.textContent=S.message||'';follow.textContent=S.following||'';time.textContent=S.total?fmt(S.pos)+' / '+fmt(S.total):'';
 fill.style.width=(S.total?100*S.pos/S.total:0)+'%';play.disabled=!S.can_play;play.textContent=S.resume?'▶ RESUME':'▶ PLAY';
 pause.textContent=S.resume?'▶ Resume':'❚❚ Pause';m_smart.className=S.mode=='smart'?'on':'';m_part.className=S.mode=='part'?'on':'';
 if(S.songs_rev!==songs.rev){songs=await api('/api/songs');render()}}catch(e){if(e!=='pin'){stt.textContent='PC not reachable';dot.style.background='#c4553f'}}}
function tab(v){view=v;document.querySelectorAll('.tabs button').forEach(b=>b.className=b.dataset.v==v?'on':'');render()}
async function lib(){const q=document.getElementById('q').value.trim();if(!q){msg.textContent='Type a song name first.';return}
 tab('lib');list.innerHTML='<div>Searching…</div>';const r=await api('/api/search?q='+encodeURIComponent(q));songs.lib=r.hits;render()}
function render(){const q=document.getElementById('q').value.toLowerCase().split(' ').filter(x=>x);let it=(songs[view]||[]).slice();
 if(view!='lib'&&q.length)it=it.filter(s=>q.every(w=>s.name.toLowerCase().includes(w)));
 if(SORT=='size')it.sort((a,b)=>(b.size||0)-(a.size||0));sortb.textContent=SORT=='size'?'Sort: Size':'Sort: Name';
 list.innerHTML='';it.forEach(s=>{const d=document.createElement('div'),n=document.createElement('span'),b=document.createElement('button');
 n.className='nm';n.textContent=s.name;const sub=[SORT=='size'&&s.size?kb(s.size):'',s.where||''].filter(x=>x).join(' · ');
 if(sub){const m=document.createElement('small');m.textContent=sub;n.appendChild(m)}
 b.className='star'+(s.fav?' on':'');b.textContent=s.fav?'★':'☆';
 b.onclick=async e=>{e.stopPropagation();s.fav=!s.fav;b.className='star'+(s.fav?' on':'');b.textContent=s.fav?'★':'☆';await api('/api/fav',{path:s.path});songs={};poll()};
 if(S.path==s.path)d.className='sel';d.onclick=()=>{api('/api/select',{path:s.path});title.textContent=s.name;info.textContent='Reading the song…'};
 d.appendChild(n);d.appendChild(b);list.appendChild(d)})}
function cmd(c){api('/api/'+c,{})}function mode(m){api('/api/mode',{mode:m})}
function start(){document.getElementById('pin').style.display='none';document.getElementById('app').style.display='block';poll();setInterval(poll,1000)}
if(K)start();else document.getElementById('pin').style.display='block';
</script></body></html>"""


def lan_addresses():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    good = [ip for ip in ips if ip.startswith(('192.168.', '172.')) or (ip.startswith('10.') and not ip.startswith('10.2.0.'))]
    return sorted(good, key=lambda ip: (not ip.startswith('192.168.'), ip)) or sorted(ips - {'127.0.0.1'})


def serve(app, port, pin):
    """Start the remote in a thread. app must provide remote_state(), remote_songs(), remote_search(q) and
    remote_call(name, data) (run on the Tk thread via app.remote_q)."""

    FAILS = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code); self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff'); self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers(); self.wfile.write(data)

        def _ok(self, qs):
            ip, now = self.client_address[0], time.time()
            fails = [t for t in FAILS.get(ip, []) if now - t < 60]
            if len(fails) >= 5:                       # 5 wrong PINs in a minute: lock this device out for a minute
                FAILS[ip] = fails
                return False
            if qs.get('k', [''])[0] == pin:
                return True
            FAILS[ip] = fails + [now]
            return False

        def _on_tk(self, fn, *args):
            box, done = {}, threading.Event()
            def run():
                try:
                    box['r'] = fn(*args)
                except Exception as e:  # noqa: BLE001
                    box['r'] = {'error': str(e)}
                done.set()
            app.remote_q.put(run)
            done.wait(10)
            return box.get('r', {'error': 'busy'})

        def do_GET(self):
            u = urlparse(self.path); qs = parse_qs(u.query)
            if u.path in ('/', '/index.html'):
                return self._send(200, PAGE.encode(), 'text/html; charset=utf-8')
            if not self._ok(qs):
                return self._send(403, {'error': 'pin'})
            if u.path == '/api/state':
                return self._send(200, self._on_tk(app.remote_state))
            if u.path == '/api/songs':
                return self._send(200, self._on_tk(app.remote_songs))
            if u.path == '/api/search':
                return self._send(200, {'hits': app.remote_search(qs.get('q', [''])[0])})
            self._send(404, {'error': 'unknown'})

        def do_POST(self):
            u = urlparse(self.path); qs = parse_qs(u.query)
            if not self._ok(qs):
                return self._send(403, {'error': 'pin'})
            try:
                data = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            except ValueError:
                data = {}
            self._send(200, self._on_tk(app.remote_call, u.path.rsplit('/', 1)[-1], data))

    srv = ThreadingHTTPServer(('0.0.0.0', port), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
