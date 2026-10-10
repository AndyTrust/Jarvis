import subprocess,json,time,sys
m=sys.argv[1]
p=subprocess.Popen(["claude","-p","--input-format","stream-json","--output-format","stream-json","--verbose","--model",m,"--setting-sources","project","--strict-mcp-config","--mcp-config",'{"mcpServers":{}}'],cwd=__import__("tempfile").mkdtemp(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
t_av=time.time()
for i in range(4):
    if i==0: time.sleep(3)  # lascia finire l'avvio, come un processo sempre vivo
    s=time.time(); prima=None
    p.stdin.write(json.dumps({"type":"user","message":{"role":"user","content":"rispondi solo ok"}})+"\n"); p.stdin.flush()
    while True:
        l=p.stdout.readline()
        if not l: break
        d=json.loads(l)
        if d.get("type")=="assistant" and prima is None: prima=time.time()
        if d.get("type")=="result":
            print(m,"turno",i+1,"primo_messaggio_ms",int((prima-s)*1000) if prima else None,"totale_ms",int((time.time()-s)*1000),"api",d.get("duration_api_ms")); break
p.stdin.close(); p.wait()
