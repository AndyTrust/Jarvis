# Telefono (facoltativo)

Due modi, indipendenti.

## 1. Il telefono Android visto dal Mac (ADB)

Jarvis vede lo schermo del telefono e ci tocca sopra dal Mac, sulla stessa rete Wi-Fi.

1. Rispondi «sì» al telefono nelle domande di avvio: l'installatore mette `adb` e `scrcpy` (gruppo `telefono` del Brewfile).
2. Sul telefono: Impostazioni → Info sul telefono → tocca 7 volte «Numero build» → Opzioni sviluppatore → **Debug wireless**.
3. Sul Mac: «Associa dispositivo con codice» e `adb pair <indirizzo>:<porta>`, poi `adb connect <indirizzo>:<porta>`.
4. Controlla: `adb devices` deve mostrare il telefono come `device`.

Regole: ogni tocco è un'azione vera sul telefono; Jarvis prima legge lo schermo (`adb shell uiautomator dump`), poi tocca,
e chiede conferma prima di inviare, comprare o cancellare. Funziona con qualunque Android con il Debug wireless
(Android 11 o più nuovo); con Android più vecchi serve il cavo USB la prima volta (`adb tcpip 5555`).

## 2. L'app Android di Jarvis

L'app per il telefono è una distribuzione a parte (repository «Jarvis Telefono»), con la sua guida di installazione.
Usa la stessa memoria se la colleghi alla tua VPS o al Mac: vedi la sua documentazione.

## Spento finché non lo configuri

Senza `adb` o senza un telefono collegato la spia «Android» del pannello resta grigia con il motivo. Il resto funziona.
