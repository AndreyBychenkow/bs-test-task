"""
Заготовка сервиса — ждём ТЗ.
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Test Task Service")

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сервис на связи</title>
<style>
  html,body{margin:0;height:100%;background:#0b0f17;color:#e6ecf5;
    font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;display:flex;
    align-items:center;justify-content:center}
  .card{max-width:560px;padding:40px;border:1px solid #1e2836;border-radius:18px;
    background:#0f1520;text-align:center}
  h1{margin:0 0 10px;font-size:22px}
  p{margin:8px 0;color:#8ea0b8;line-height:1.5}
  .ok{display:inline-block;margin-bottom:14px;padding:6px 12px;border-radius:99px;
    background:#0e2a1e;color:#43d17a;font-size:13px;border:1px solid #1c5137}
  code{background:#151d2b;padding:2px 6px;border-radius:6px;color:#7cc4ff}
</style></head>
<body><div class="card">
  <div class="ok">● сервис запущен</div>
  <h1>Платформа готова к деплою</h1>
  <p>Health-check: <code>/health</code></p>
  <p>Как только придёт текст задания — сервис будет собран и задеплоен на публичный URL.</p>
</div></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
