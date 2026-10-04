import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core import config
from app.core.migrate import jalankan_migrasi
from app.routers import (auth, dashboard, transaksi, segmentasi, forecasting, performa, pengguna,
                         eda, master, laporan, data_import)

jalankan_migrasi()

app = FastAPI(
    title="Kencana Analytics API",
    description="Backend untuk sistem analisis Big Data Kencana Travel — "
                 "segmentasi pasar, forecasting demand, dan analisis performa rute.",
    version="1.0.0",
)

# Hanya frontend yang boleh memanggil API dari browser. CORS_ORIGINS (dipisah koma) bisa
# dipakai untuk menambah origin lain; default-nya FRONTEND_URL + Vite dev server lokal.
_origins_env = os.getenv("CORS_ORIGINS", "")
ALLOWED_ORIGINS = ([o.strip().rstrip("/") for o in _origins_env.split(",") if o.strip()]
                   or [config.FRONTEND_URL, "http://localhost:5173", "http://127.0.0.1:5173"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transaksi.router)
app.include_router(segmentasi.router)
app.include_router(forecasting.router)
app.include_router(performa.router)
app.include_router(pengguna.router)
app.include_router(eda.router)
app.include_router(master.router)
app.include_router(laporan.router)
app.include_router(data_import.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "Kencana Analytics API", "docs": "/docs"}
