"""Serve the demo SPA and API on loopback behind a private SSH tunnel."""
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sre_agent.catalog.app import app

root = Path(__file__).resolve().parents[2] / 'apps' / 'demo_shop' / 'dist'
app.mount('/assets', StaticFiles(directory=root / 'assets'), name='assets')
@app.get('/', include_in_schema=False)
@app.get('/presenter', include_in_schema=False)
@app.get('/mission-control', include_in_schema=False)
def index():
    return FileResponse(root / 'index.html', headers={'Cache-Control': 'no-store'})
