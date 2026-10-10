# Jarvis in Docker (template)

*Creato: 2026-09-26 16:40 · provato sul template Jarvis-Privato-Test*

Serve a provare il template su una macchina pulita, senza toccare il Mac.

1. Dalla radice del template: `docker build -f docker/Dockerfile.template -t jarvis-template .`
2. Avvio: `docker run -d --name jarvis -p 7777:7777 jarvis-template` (porta di fuori = porta di dentro).
3. Pagina: `http://127.0.0.1:7777`. Il token cambia a ogni avvio ed è già dentro la pagina.
4. Claude Code: `docker exec -it jarvis claude` e si fa il login la prima volta.
5. Voce, volto, telefono, Android, VPS e memoria su OneDrive dentro il contenitore restano spenti: le spie lo dicono.
6. Fine prova: `docker rm -f jarvis && docker rmi jarvis-template`.
