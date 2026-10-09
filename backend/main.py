"""
Simulador de Cartera v2 — Backend FastAPI
Punto de entrada principal
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from models import init_db
from market import random_walk_loop
from routers import auth, docente, grupos


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar DB y datos seed
    init_db()
    # Lanzar el loop del mercado en background
    task = asyncio.create_task(random_walk_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Simulador de Cartera — FCE UNICEN",
    version="2.0.0",
    lifespan=lifespan
)

# CORS — permite el frontend desde cualquier origen (Moodle)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(docente.router)
app.include_router(grupos.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


# Servir el frontend estático (si está en /static)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str = ""):
        index = os.path.join(static_dir, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        return {"detail": "Frontend no encontrado"}
