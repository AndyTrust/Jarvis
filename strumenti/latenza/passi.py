import json,re,statistics as st
from datetime import datetime
def tj(s): return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
def td(s): return datetime.fromisoformat(s[:26]+'+00:00').timestamp()
rows=[json.loads(l) for l in open(''+__import__('sys').argv[1]+'')]
dk=[(td(l[:30].split(' ')[0]),l[31:].strip()) for l in open('vps24.txt',errors='replace') if l[:4]=='2026']
sends=[t for t,x in dk if x.startswith('[tool] ->')]; backs=[t for t,x in dk if x.startswith('[tool] <-')]
steps=[];mcp_out=[];mcp_back=[]
prev=None
for r in rows:
    if not r.get('timestamp'): continue
    t=tj(r['timestamp'])
    if r['type']=='user': prev=t; prevkind='U'
    if r['type']=='assistant':
        for c in r['message']['content']:
            if c['type']=='tool_use' and c['name'].startswith('mcp__phone'):
                s=[x for x in sends if t-0.5<x<t+5]
                if s: mcp_out.append(s[0]-t)
    if r['type']=='user' and not isinstance(r['message']['content'],str):
        b=[x for x in backs if t-5<x<=t+0.5]
        if b and t>1791380000-1e9: mcp_back.append(t-b[-1])
# step durations: from a user/tool_result to last entry of the assistant message id
cur=None;start=None;last=None;out=[]
for r in rows:
    if not r.get('timestamp'): continue
    t=tj(r['timestamp'])
    if r['type']=='user':
        if cur: out.append((last-start, cur[1], cur[2]))
        cur=None; start=t
    elif r['type']=='assistant' and start:
        mid=r['message']['id']; u=r['message']['usage']
        if not cur or cur[0]!=mid: 
            if cur: out.append((last-start,cur[1],cur[2])); start=last
            cur=(mid,u.get('output_tokens'),u.get('cache_read_input_tokens',0)>0)
        last=t
def q(l): l=sorted(l); return f"n={len(l)} med={st.median(l):.2f} p90={l[int(len(l)*.9)]:.2f} max={max(l):.2f}"
print("passo modello (s) tutti:",q([o[0] for o in out]))
print("passo modello cache calda, out<200 tok:",q([o[0] for o in out if o[2] and o[1]<200]))
print("passo modello cache calda, out 200-500:",q([o[0] for o in out if o[2] and 200<=o[1]<500]))
print("passo modello cache fredda:",[round(o[0],2) for o in out if not o[2]])
print("MCP tool_use -> [tool] -> (s):",q(mcp_out))
print("[tool] <- -> tool_result in sessione (s):",q(mcp_back))
