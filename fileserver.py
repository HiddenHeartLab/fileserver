#!/usr/bin/env python3
"""
Read-only research file browser.
Renders Markdown+LaTeX, syntax-highlights code, displays images, renders notebooks.
VTK/VTP/VTU files rendered interactively via Three.js (server-side mesh extraction).

Usage:
    uvicorn fileserver:app --host 0.0.0.0 --port 8080
"""

import base64
import json
import os
import re
import html as html_lib
from pathlib import Path

import markdown as md_lib
import numpy as np
import pyvista as pv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

pv.set_error_output_file("/dev/null")   # suppress pyvista stderr noise

ROOT = Path(os.environ.get("FILESERVER_ROOT", Path.home())).resolve()
app = FastAPI()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tiff", ".tif"}
CODE_EXTS  = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".r", ".jl", ".m", ".c", ".cpp",
    ".h", ".hpp", ".java", ".go", ".rs", ".sh", ".bash", ".zsh", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".css", ".sql", ".xml", ".tex", ".bib",
    ".log", ".csv", ".txt", ".f90", ".f95", ".f",
}
VTK_EXTS = {".vtp", ".vtu", ".vtk", ".vts", ".vtr"}

_MD_EXTS = ["tables", "fenced_code", "attr_list"]

# ── markdown helper ───────────────────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """Render markdown to HTML, preserving $...$ and $$...$$ for client-side KaTeX."""
    saved: list[str] = []
    def save(m: re.Match) -> str:
        i = len(saved)
        saved.append(m.group(0))
        return f"ZZMATH{i}ZZ"
    text = re.sub(r"\$\$[\s\S]*?\$\$", save, text)
    text = re.sub(r"\$[^\$\n]+?\$", save, text)
    html = md_lib.markdown(text, extensions=_MD_EXTS)
    for i, expr in enumerate(saved):
        html = html.replace(f"ZZMATH{i}ZZ", expr)
    return html


# ── path helpers ──────────────────────────────────────────────────────────────

def safe_path(rel: str) -> Path:
    path = (ROOT / rel.lstrip("/")).resolve()
    if not str(path).startswith(str(ROOT.resolve())):
        raise HTTPException(403)
    return path


def breadcrumbs(rel: str) -> str:
    parts = [p for p in rel.strip("/").split("/") if p]
    crumbs = ['<a href="/">repos</a>']
    for i, part in enumerate(parts):
        href = "/browse/" + "/".join(parts[: i + 1])
        crumbs.append(f'<a href="{href}">{html_lib.escape(part)}</a>')
    return " / ".join(crumbs)


def file_nav(rel: str) -> str:
    return (
        f'<nav>{breadcrumbs(rel)}'
        f'<a class="dl-link" href="/download/{rel}">⬇ Download</a></nav>'
    )


def file_icon(p: Path) -> str:
    if p.is_dir():
        return "📁"
    icons = {
        ".md": "📝", ".ipynb": "📓", ".pdf": "📄",
        ".py": "🐍", ".r": "📊", ".jl": "🔬", ".m": "⚙️",
        ".tex": "🧮", ".bib": "📚",
        ".vtp": "🧊", ".vtu": "🧊", ".vtk": "🧊", ".vts": "🧊", ".vtr": "🧊",
    }
    if p.suffix.lower() in IMAGE_EXTS:
        return "🖼"
    return icons.get(p.suffix.lower(), "📄")


# ── standard page template ────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: #f7f7f7; color: #1a1a1a; }
#wrap { max-width: 980px; margin: 0 auto; padding: 1.5rem 1rem; }
nav { font-size: .85rem; color: #888; margin-bottom: 1.2rem; }
nav a { color: #0057d8; text-decoration: none; }
nav a:hover { text-decoration: underline; }
.dir { list-style: none; background: #fff; border: 1px solid #e2e2e2;
       border-radius: 8px; overflow: hidden; }
.dir li { border-bottom: 1px solid #f0f0f0; }
.dir li:last-child { border-bottom: none; }
.dir li { display: flex; align-items: stretch; }
.dir .row-name { flex: 1; display: flex; align-items: center; gap: .6rem;
                 padding: .52rem 1rem; color: #0057d8; text-decoration: none; font-size: .92rem; }
.dir .row-name:hover { background: #f0f5ff; }
.dir .row-dl { display: flex; align-items: center; padding: .52rem 1rem;
               color: #888; text-decoration: none; font-size: 1rem; }
.dir .row-dl:hover { color: #0057d8; background: #f0f5ff; }
.dl-link { margin-left: 1rem; color: #0057d8; text-decoration: none; }
.dl-link:hover { text-decoration: underline; }
.icon { width: 1.2rem; text-align: center; }
.panel { background: #fff; border: 1px solid #e2e2e2; border-radius: 8px; padding: 2rem; }
.md h1, .md h2, .md h3, .md h4 { margin: 1.6rem 0 .5rem; line-height: 1.3; }
.md h1 { font-size: 1.75rem; border-bottom: 1px solid #eee; padding-bottom: .4rem; }
.md h2 { font-size: 1.35rem; border-bottom: 1px solid #eee; padding-bottom: .3rem; }
.md h3 { font-size: 1.1rem; }
.md p  { margin: .85rem 0; line-height: 1.75; }
.md ul, .md ol { margin: .6rem 0 .6rem 1.6rem; }
.md li { margin: .25rem 0; line-height: 1.65; }
.md code { background: #f3f3f3; padding: .1em .35em; border-radius: 3px;
           font-size: .88em; font-family: "SFMono-Regular", Consolas, monospace; }
.md pre  { background: #f6f8fa; border: 1px solid #e0e0e0; border-radius: 6px;
           padding: 1rem 1.2rem; overflow-x: auto; margin: 1rem 0; }
.md pre code { background: none; padding: 0; font-size: .87rem; line-height: 1.5; }
.md blockquote { border-left: 3px solid #ccc; margin: 1rem 0; padding: .5rem 1rem; color: #555; }
.md table { border-collapse: collapse; margin: 1rem 0; }
.md th, .md td { border: 1px solid #ddd; padding: .4rem .8rem; }
.md th { background: #f5f5f5; }
.md img { max-width: 100%; border-radius: 4px; }
.md a   { color: #0057d8; }
.md hr  { border: none; border-top: 1px solid #eee; margin: 1.5rem 0; }
.code pre { margin: 0; overflow-x: auto; }
.code code { font-size: .87rem; line-height: 1.55;
             font-family: "SFMono-Regular", Consolas, monospace; }
.img-panel { text-align: center; }
.img-panel img { max-width: 100%; border-radius: 4px; }
.nb-cell   { margin-bottom: 1.2rem; }
.nb-code   { background: #f6f8fa; border: 1px solid #e0e0e0; border-radius: 6px;
             padding: .8rem 1rem; overflow-x: auto; }
.nb-code code { font-size: .87rem; line-height: 1.5; }
.nb-out    { margin-top: .4rem; padding: .4rem 1rem; border-left: 3px solid #ddd;
             font-size: .87rem; font-family: monospace; white-space: pre-wrap; color: #444; }
.nb-out img { max-width: 100%; display: block; margin-top: .3rem; }
"""

_HEAD = """
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
"""

_RENDER_JS = """
<script>
function applyMathAndHighlight(root) {
  root.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
  renderMathInElement(root, {
    delimiters: [
      {left:'$$', right:'$$', display:true},
      {left:'$',  right:'$',  display:false},
      {left:'\\\\[', right:'\\\\]', display:true},
      {left:'\\\\(', right:'\\\\)', display:false}
    ],
    throwOnError: false
  });
}
</script>
"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_lib.escape(title)}</title>
{_HEAD}
{_RENDER_JS}
<style>{_CSS}</style>
</head>
<body><div id="wrap">{body}</div></body>
</html>""")


# ── VTK viewer ────────────────────────────────────────────────────────────────

_VTK_CSS = """\
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1e1e2e; overflow: hidden;
       font-family: -apple-system, "Segoe UI", sans-serif; color: #cdd6f4; }
#topbar { position: fixed; top: 0; left: 0; right: 0; height: 38px; z-index: 10;
          background: rgba(30,30,46,.96); display: flex; align-items: center;
          gap: .8rem; padding: 0 1rem; font-size: .82rem; border-bottom: 1px solid #45475a; }
#topbar a { color: #89b4fa; text-decoration: none; }
#topbar a:hover { text-decoration: underline; }
#viewport { position: fixed; top: 38px; left: 0; right: 0; bottom: 0; }
#panel { position: fixed; top: 48px; right: 12px; background: rgba(24,24,37,.94);
         border: 1px solid #45475a; border-radius: 8px; padding: .7rem 1rem;
         font-size: .82rem; min-width: 195px; display: flex; flex-direction: column;
         gap: .55rem; }
#panel label { display: flex; align-items: center; gap: .5rem; cursor: pointer; }
#panel select { font-size: .82rem; background: #313244; color: #cdd6f4;
                border: 1px solid #585b70; border-radius: 4px; padding: .15rem .35rem; flex: 1; }
#info { color: #9399b2; font-size: .78rem; line-height: 1.5; }
#colorbar { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
            background: rgba(24,24,37,.93); border: 1px solid #45475a; border-radius: 6px;
            padding: .4rem .8rem; display: none; align-items: center; gap: .6rem; font-size: .78rem; }
#cb-canvas { width: 160px; height: 14px; border-radius: 3px; display: block; }
#cb-label  { color: #cdd6f4; min-width: 70px; text-align: center; }
#loading   { position: fixed; inset: 0; background: rgba(14,14,22,.88); color: #cdd6f4;
             display: flex; align-items: center; justify-content: center;
             font-size: 1rem; z-index: 100; letter-spacing: .02em; }
</style>"""

# The Three.js viewer script (raw string — no Python escape processing)
_VTK_JS = r"""
(async function () {
  const loading  = document.getElementById('loading');
  const infoEl   = document.getElementById('info');
  const viewport = document.getElementById('viewport');

  // ── fetch geometry JSON from server ──────────────────────────────────────
  let geom;
  try {
    const r = await fetch(GEOM_URL);
    if (!r.ok) throw new Error((await r.text()) || 'HTTP ' + r.status);
    geom = await r.json();
  } catch (e) {
    loading.textContent = '⚠ ' + e.message;
    return;
  }
  loading.style.display = 'none';
  infoEl.textContent = geom.n_points.toLocaleString() + ' pts · ' + geom.n_cells.toLocaleString() + ' cells';

  // ── decode base64 → typed arrays ─────────────────────────────────────────
  function b64buf(str) {
    const bin = atob(str), n = bin.length, buf = new ArrayBuffer(n), v = new Uint8Array(buf);
    for (let i = 0; i < n; i++) v[i] = bin.charCodeAt(i);
    return buf;
  }
  const pts = new Float32Array(b64buf(geom.points));
  const idx = new Uint32Array(b64buf(geom.indices));

  // ── Three.js scene ────────────────────────────────────────────────────────
  const W = () => viewport.clientWidth, H = () => viewport.clientHeight;

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(devicePixelRatio);
  renderer.setSize(W(), H());
  viewport.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1e1e2e);

  const camera = new THREE.PerspectiveCamera(45, W() / H(), 1e-5, 1e6);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const sun  = new THREE.DirectionalLight(0xffffff, 0.85); sun.position.set(1, 2, 3);  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xffffff, 0.30); fill.position.set(-2,-1,-2); scene.add(fill);

  // build geometry
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pts, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();

  // center & fit to view
  geo.computeBoundingBox();
  const bb = geo.boundingBox;
  const ctr = new THREE.Vector3(); bb.getCenter(ctr);
  const sz  = new THREE.Vector3(); bb.getSize(sz);
  const sc  = 2.0 / Math.max(sz.x, sz.y, sz.z);
  geo.translate(-ctr.x, -ctr.y, -ctr.z);
  geo.scale(sc, sc, sc);
  camera.position.set(0, 0, 3.5);
  controls.update();

  const mat = new THREE.MeshPhongMaterial({ color: 0x5599ee, side: THREE.DoubleSide, shininess: 25 });
  const mesh = new THREE.Mesh(geo, mat);
  scene.add(mesh);

  // ── scalar coloring ───────────────────────────────────────────────────────
  const scalarNames = Object.keys(geom.scalars || {});
  const sel = document.getElementById('scalar-sel');
  scalarNames.forEach(n => { const o = document.createElement('option'); o.value = o.textContent = n; sel.add(o); });

  const decoded = {};
  scalarNames.forEach(n => { decoded[n] = new Float32Array(b64buf(geom.scalars[n])); });

  function applyScalar(name) {
    if (!name) {
      geo.deleteAttribute('color'); mat.vertexColors = false; mat.color.set(0x5599ee); mat.needsUpdate = true;
      drawColorbar(null); return;
    }
    const arr = decoded[name], n = pts.length / 3;
    let mn = Infinity, mx = -Infinity;
    for (let i = 0; i < arr.length; i++) { if (arr[i] < mn) mn = arr[i]; if (arr[i] > mx) mx = arr[i]; }
    const rng = mx - mn || 1, cols = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const [r, g, b] = viridis((arr[i] - mn) / rng);
      cols[i*3] = r; cols[i*3+1] = g; cols[i*3+2] = b;
    }
    geo.setAttribute('color', new THREE.BufferAttribute(cols, 3));
    mat.vertexColors = true; mat.needsUpdate = true;
    drawColorbar(mn, mx, name);
  }

  sel.addEventListener('change', () => applyScalar(sel.value));
  if (scalarNames.length) { sel.value = scalarNames[0]; applyScalar(scalarNames[0]); }

  // wireframe toggle
  document.getElementById('wf-cb').addEventListener('change', e => { mat.wireframe = e.target.checked; });

  // resize
  window.addEventListener('resize', () => {
    camera.aspect = W() / H(); camera.updateProjectionMatrix(); renderer.setSize(W(), H());
  });

  // render loop
  (function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

  // ── colorbar ──────────────────────────────────────────────────────────────
  function drawColorbar(mn, mx, name) {
    const cb = document.getElementById('colorbar');
    if (mn === null) { cb.style.display = 'none'; return; }
    cb.style.display = 'flex';
    document.getElementById('cb-min').textContent   = fmt(mn);
    document.getElementById('cb-max').textContent   = fmt(mx);
    document.getElementById('cb-label').textContent = name || '';
    const canvas = document.getElementById('cb-canvas'), ctx = canvas.getContext('2d');
    canvas.width = 200;
    for (let x = 0; x < 200; x++) {
      const [r, g, b] = viridis(x / 200);
      ctx.fillStyle = `rgb(${r*255|0},${g*255|0},${b*255|0})`; ctx.fillRect(x, 0, 1, canvas.height);
    }
  }

  function fmt(v) {
    if (v === 0) return '0';
    return (Math.abs(v) >= 1000 || Math.abs(v) < 0.01) ? v.toExponential(2) : v.toPrecision(4);
  }

  // ── viridis colormap ──────────────────────────────────────────────────────
  function viridis(t) {
    const c = [[.267,.005,.329],[.283,.301,.559],[.167,.553,.557],[.477,.821,.318],[.993,.906,.144]];
    t = Math.max(0, Math.min(1, t));
    const n = c.length - 1, i = Math.min(t * n | 0, n - 1), f = t * n - i;
    return [c[i][0]+f*(c[i+1][0]-c[i][0]), c[i][1]+f*(c[i+1][1]-c[i][1]), c[i][2]+f*(c[i+1][2]-c[i][2])];
  }

})();
"""


def _vtk_page(name: str, rel: str) -> str:
    nav    = breadcrumbs(rel)
    geom_url = json.dumps("/vtk-json/" + rel)
    return (
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_lib.escape(name)}</title>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
{_VTK_CSS}
</head>
<body>
<div id="topbar"><nav>{nav}</nav><a href="/download/{rel}">⬇ Download</a><span id="info" style="margin-left:auto"></span></div>
<div id="viewport"></div>
<div id="panel">
  <label>Color by
    <select id="scalar-sel"><option value="">Solid</option></select>
  </label>
  <label><input type="checkbox" id="wf-cb"> Wireframe</label>
</div>
<div id="colorbar">
  <span id="cb-min"></span>
  <canvas id="cb-canvas" width="200" height="14"></canvas>
  <span id="cb-max"></span>
  <span id="cb-label"></span>
</div>
<div id="loading">Loading {html_lib.escape(name)}…</div>
<script>
const GEOM_URL = {geom_url};
"""
        + _VTK_JS
        + """
</script>
</body>
</html>"""
    )


def _load_vtk_geometry(path: Path) -> dict:
    mesh = pv.read(str(path))

    # For volume meshes (UnstructuredGrid), extract the outer surface
    if isinstance(mesh, pv.UnstructuredGrid):
        mesh = mesh.extract_surface()

    # Triangulate so every face is a triangle
    mesh = mesh.triangulate()

    pts = mesh.points.astype(np.float32)                  # (N, 3)
    faces = mesh.faces.reshape(-1, 4)[:, 1:].astype(np.uint32)  # (M, 3), skip leading '3'

    # Collect scalar point-data fields (1-component, or norm of vectors)
    scalars: dict[str, str] = {}
    for name, arr in mesh.point_data.items():
        arr = np.asarray(arr, dtype=np.float64)
        if arr.ndim == 2:
            arr = np.linalg.norm(arr, axis=1)   # vector → magnitude
        if arr.ndim == 1:
            scalars[name] = base64.b64encode(arr.astype(np.float32).tobytes()).decode()

    return {
        "n_points": int(len(pts)),
        "n_cells":  int(len(faces)),
        "points":   base64.b64encode(pts.tobytes()).decode(),
        "indices":  base64.b64encode(faces.tobytes()).decode(),
        "scalars":  scalars,
    }


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return await browse("")


@app.get("/browse", response_class=HTMLResponse)
@app.get("/browse/{rel:path}", response_class=HTMLResponse)
async def browse(rel: str = ""):
    path = safe_path(rel)
    if not path.exists():
        raise HTTPException(404)
    if path.is_dir():
        return _render_dir(path, rel)
    return _render_file(path, rel)


@app.get("/raw/{rel:path}")
async def raw(rel: str):
    path = safe_path(rel)
    if not path.exists() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/download/{rel:path}")
async def download(rel: str):
    path = safe_path(rel)
    if not path.exists() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=path.name)


@app.get("/vtk-json/{rel:path}")
async def vtk_json(rel: str):
    path = safe_path(rel)
    if not path.exists() or not path.is_file():
        raise HTTPException(404)
    try:
        data = _load_vtk_geometry(path)
    except Exception as e:
        raise HTTPException(500, str(e))
    return JSONResponse(data)


# ── renderers ─────────────────────────────────────────────────────────────────

def _render_dir(path: Path, rel: str) -> HTMLResponse:
    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    rows = []
    for e in entries:
        if e.name.startswith(".") or e.name in {"__pycache__"}:
            continue
        icon   = file_icon(e)
        suffix = "/" if e.is_dir() else ""
        view_href = ("/browse/" + rel + "/" + e.name).replace("//", "/")
        name_link = (
            f'<a class="row-name" href="{view_href}">'
            f'<span class="icon">{icon}</span>'
            f'{html_lib.escape(e.name)}{suffix}</a>'
        )
        if e.is_dir():
            rows.append(f'<li>{name_link}</li>')
        else:
            dl_href = ("/download/" + rel + "/" + e.name).replace("//", "/")
            rows.append(
                f'<li>{name_link}'
                f'<a class="row-dl" href="{dl_href}" title="Download">⬇</a></li>'
            )
    body = (
        f'<nav>{breadcrumbs(rel)}</nav>'
        f'<ul class="dir">{"".join(rows) or "<li><a>(empty)</a></li>"}</ul>'
    )
    return page(path.name or "repos", body)


def _render_file(path: Path, rel: str) -> HTMLResponse:
    ext = path.suffix.lower()

    if ext in VTK_EXTS:
        return HTMLResponse(_vtk_page(path.name, rel))

    if ext in IMAGE_EXTS:
        body = (
            f'{file_nav(rel)}'
            f'<div class="panel img-panel">'
            f'<img src="/raw/{rel}" alt="{html_lib.escape(path.name)}"></div>'
        )
        return page(path.name, body)

    if ext == ".pdf":
        return FileResponse(path)

    if ext == ".ipynb":
        return _render_notebook(path, rel)

    if ext == ".md":
        return _render_markdown(path, rel)

    if ext in CODE_EXTS:
        try:
            content = path.read_text(errors="replace")
        except Exception:
            raise HTTPException(500)
        lang = ext.lstrip(".") or "plaintext"
        body = (
            f'{file_nav(rel)}'
            f'<div class="panel code"><pre>'
            f'<code class="language-{lang}">{html_lib.escape(content)}</code>'
            f'</pre></div>'
            f"<script>hljs.highlightAll();</script>"
        )
        return page(path.name, body)

    return FileResponse(path)


def _render_markdown(path: Path, rel: str) -> HTMLResponse:
    try:
        content = path.read_text(errors="replace")
    except Exception:
        raise HTTPException(500)
    rendered = _md_to_html(content)
    body = (
        f'{file_nav(rel)}'
        f'<div class="panel"><div class="md" id="md">{rendered}</div></div>'
        f"<script>applyMathAndHighlight(document.getElementById('md'));</script>"
    )
    return page(path.name, body)


def _render_notebook(path: Path, rel: str) -> HTMLResponse:
    try:
        nb = json.loads(path.read_text(errors="replace"))
    except Exception:
        raise HTTPException(500, "Could not parse notebook")

    cells_html: list[str] = []

    for cell in nb.get("cells", []):
        ct  = cell.get("cell_type", "")
        src = "".join(cell.get("source", []))

        if ct == "markdown":
            cells_html.append(
                f'<div class="nb-cell"><div class="md">{_md_to_html(src)}</div></div>'
            )

        elif ct == "code":
            outs = []
            for out in cell.get("outputs", []):
                ot   = out.get("output_type", "")
                data = out.get("data", {})
                if ot in ("stream", "error"):
                    text = "".join(out.get("text", out.get("traceback", [])))
                    outs.append(f'<div class="nb-out">{html_lib.escape(text)}</div>')
                elif ot in ("display_data", "execute_result"):
                    if "image/png" in data:
                        b64 = data["image/png"]
                        if isinstance(b64, list): b64 = "".join(b64)
                        outs.append(f'<div class="nb-out"><img src="data:image/png;base64,{b64}"></div>')
                    elif "image/svg+xml" in data:
                        svg = data["image/svg+xml"]
                        if isinstance(svg, list): svg = "".join(svg)
                        outs.append(f'<div class="nb-out">{svg}</div>')
                    elif "text/html" in data:
                        h = data["text/html"]
                        if isinstance(h, list): h = "".join(h)
                        outs.append(f'<div class="nb-out">{h}</div>')
                    elif "text/plain" in data:
                        txt = data["text/plain"]
                        if isinstance(txt, list): txt = "".join(txt)
                        outs.append(f'<div class="nb-out">{html_lib.escape(txt)}</div>')
            cells_html.append(
                f'<div class="nb-cell">'
                f'<div class="nb-code"><pre>'
                f'<code class="language-python">{html_lib.escape(src)}</code>'
                f'</pre></div>'
                f'{"".join(outs)}</div>'
            )

    body = (
        f'{file_nav(rel)}'
        f'<div class="panel" id="nb">{"".join(cells_html)}</div>'
        f"<script>applyMathAndHighlight(document.getElementById('nb'));</script>"
    )
    return page(path.name, body)
