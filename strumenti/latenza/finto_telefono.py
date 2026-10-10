# Finto telefono per misurare la catena VPS: manda user_message e risponde ai tool_call
# con esiti sintetici (nessuna azione vera, nessun invio). Token da env PT, mai stampato.
import asyncio,json,os,sys,time
import websockets
URL="wss://vps.esempio.it/phone"
def ms(): return int(time.time()*1000)
FINTI={
 "apri_app":{"aperto":True,"app_in_primo_piano":"com.spotify.music","descrizione":"app Spotify"},
 "open_app":{"aperto":True,"app_in_primo_piano":"com.spotify.music"},
 "cerca_google":{"aperto":True,"app_in_primo_piano":"com.google.android.googlequicksearchbox","descrizione":"ricerca Google aperta: meteo Olbia, 22 gradi, sereno"},
 "componi":{"aperto":True,"app_in_primo_piano":"com.whatsapp","descrizione":"WhatsApp verso te stesso con la bozza nel campo"},
 "read_screen":"app: com.android.settings · 3 elementi\n[1] Impostazioni\n[2] Connessioni\n[3] Display",
 "cerca_contatto":{"trovati":[{"nome":"UTENTE TITOLARE (te stesso)"}]},
}
async def giro(frasi,log):
    t0=ms(); ws=await websockets.connect(URL,open_timeout=10); t1=ms()
    await ws.send(json.dumps({"type":"auth","token":os.environ["PT"]}))
    m=json.loads(await ws.recv()); t2=ms()
    log.write(json.dumps({"ev":"ws_aperto","handshake_ms":t1-t0,"auth_ms":t2-t1,"t":t2})+"\n")
    for frase in frasi:
        ts=ms(); await ws.send(json.dumps({"type":"user_message","text":frase}))
        ev=[]; 
        while True:
            m=json.loads(await asyncio.wait_for(ws.recv(),timeout=300)); t=ms()
            if m.get("type")=="tool_call":
                a=m["command"].get("action"); ev.append((t-ts,"tool:"+a))
                if a in("invia_bozza","request_send_confirmation"):
                    await ws.send(json.dumps({"type":"tool_result","id":m["id"],"error":"L'utente ha annullato: non inviare nulla."}))
                else:
                    await ws.send(json.dumps({"type":"tool_result","id":m["id"],"result":FINTI.get(a,True)}))
            elif m.get("type")=="assistant_message":
                ev.append((t-ts,"risposta")); 
                r={"frase":frase,"invio":ts,"totale_ms":t-ts,"eventi":ev,"testo":m.get("text","")[:120]}
                print(json.dumps(r,ensure_ascii=False)); log.write(json.dumps(r,ensure_ascii=False)+"\n"); log.flush()
                break
        await asyncio.sleep(3)
    await ws.close()
frasi=sys.argv[2:]
with open(sys.argv[1],"a") as log: asyncio.run(giro(frasi,log))
