import json,re,statistics as st
from datetime import datetime
def T(s): return datetime.fromisoformat(s.replace('Z','+00:00')[:26]+'+00:00' if '.' in s else s).timestamp()
def td(s):  # docker ts 2026-10-07T15:01:00.678858178Z
    return datetime.fromisoformat(s[:26]+'+00:00').timestamp()
def tj(s): return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
dk=[]
for l in open('vps24.txt',errors='replace'):
    m=re.match(r'(\S+Z) (.*)',l)
    if m: dk.append((td(m.group(1)),m.group(2)))
rows=[json.loads(l) for l in open(''+__import__('sys').argv[1]+'')]
utenti=[(t,x) for t,x in dk if x.startswith('[chat] utente')]
risposte=[(t,x) for t,x in dk if x.startswith('[chat] jarvis') or x.startswith('[chat] errore')]
toolsend=[(t,x) for t,x in dk if x.startswith('[tool] ->')]
toolback=[(t,x) for t,x in dk if x.startswith('[tool] <-')]
enq=[tj(r['timestamp']) for r in rows if r.get('type')=='queue-operation' and r.get('operation')=='enqueue']
out=[]
for i,(tu,x) in enumerate(utenti):
    e=[q for q in enq if tu<q<tu+30]
    if not e: continue
    e=e[0]; nxt=utenti[i+1][0] if i+1<len(utenti) else 1e20
    seg=[r for r in rows if r.get('timestamp') and e<=tj(r['timestamp'])<nxt]
    U=[tj(r['timestamp']) for r in seg if r['type']=='user' and isinstance(r['message']['content'],str)][0]
    A=[r for r in seg if r['type']=='assistant']
    ids=[]; 
    for r in A:
        if r['message']['id'] not in ids: ids.append(r['message']['id'])
    firstA=tj(A[0]['timestamp']); lastA=tj(A[-1]['timestamp'])
    rj=[t for t,_ in risposte if t>lastA-1][0]
    ts=[t for t,_ in toolsend if tu<t<rj]; tb=[t for t,_ in toolback if tu<t<rj]
    names=[re.match(r'\[tool\] -> (\S+)',y).group(1) for t,y in toolsend if tu<t<rj]
    nts=sum(1 for r in A for c in r['message']['content'] if c['type']=='tool_use' and c['name']=='ToolSearch')
    # tool roundtrip phone
    rt=[b-a for a,b in zip(ts,tb)]
    # model time: sum of (assistant last entry of each id - previous user/tool_result)
    cr=A[0]['message']['usage'].get('cache_read_input_tokens'); cc=A[0]['message']['usage'].get('cache_creation_input_tokens')
    out.append(dict(ora=datetime.utcfromtimestamp(tu).strftime('%H:%M:%S'),testo=x[22:60],avvio=e-tu,primo_passo=firstA-U,passi=len(ids),toolsearch=nts,tool=names,tel_rt=[round(r,2) for r in rt],chiusura=rj-lastA,totale=rj-tu,cr=cr,cc=cc))
for o in out: print({k:(round(v,2) if isinstance(v,float) else v) for k,v in o.items()})
json.dump(out,open('turni.json','w'))
