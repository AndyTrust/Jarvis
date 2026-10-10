import subprocess,time
p=subprocess.Popen(["ssh","vps-tuo","while read l; do date +%s%3N; done"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
r=[]
for _ in range(12):
    a=time.time()*1000; p.stdin.write("x\n"); p.stdin.flush(); o=p.stdout.readline(); b=time.time()*1000
    r.append((round(b-a,1), round(int(o)-(a+b)/2,1)))
p.stdin.close(); p.wait()
r.sort(); print("vps-mac (rtt,off) migliori:", r[:4])
