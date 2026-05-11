# fileserver

Read-only research file browser for `/Users/fsc/Documents/repos`.

Renders Markdown + LaTeX, syntax-highlighted code, images, Jupyter notebooks, and VTK/VTP/VTU meshes via Three.js.

## Configuration

The directory served is controlled by the `FILESERVER_ROOT` environment variable. If unset, it defaults to the user's home directory.

```bash
export FILESERVER_ROOT=/path/to/serve
```

## Run manually

```bash
cd /path/to/fileserver
FILESERVER_ROOT=/path/to/serve uvicorn fileserver:app --host 0.0.0.0 --port 8080
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

## Run at login (Linux systemd)

**Install:**

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/fileserver.service <<EOF
[Unit]
Description=Research file browser

[Service]
Environment=FILESERVER_ROOT=/path/to/serve
WorkingDirectory=/path/to/fileserver
ExecStart=/path/to/uvicorn fileserver:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now fileserver.service
```

Replace `/path/to/fileserver` and `/path/to/uvicorn` with the actual paths (`pwd` and `which uvicorn`).

**Check status / logs:**

```bash
systemctl --user status fileserver
journalctl --user -u fileserver -f
```

**Stop / uninstall:**

```bash
systemctl --user disable --now fileserver.service
```
