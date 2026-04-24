# fileserver

Read-only research file browser for `/Users/fsc/Documents/repos`.

Renders Markdown + LaTeX, syntax-highlighted code, images, Jupyter notebooks, and VTK/VTP/VTU meshes via Three.js.

## Run manually

```bash
cd /Users/fsc/Documents/repos/fileserver
uvicorn fileserver:app --host 0.0.0.0 --port 8080
```

Then open http://localhost:8080.

## Install dependencies

```bash
pip install -r requirements.txt
```

## Run at login (macOS launchd)

**Install:**

```bash
cp com.fsc.fileserver.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.fsc.fileserver.plist
```

**Check status:**

```bash
launchctl list | grep fileserver
```

**Logs:**

```bash
tail -f ~/Library/Logs/fileserver.log
tail -f ~/Library/Logs/fileserver.err
```

**Stop / uninstall:**

```bash
launchctl unload ~/Library/LaunchAgents/com.fsc.fileserver.plist
```
