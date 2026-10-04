from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_cabang_scope
from app.services import eda_service as svc

router = APIRouter(prefix="/api/eda", tags=["Eksplorasi Data (EDA)"])


@router.get("")
def eda(tanggal_mulai: date | None = Query(None, description="Batas awal tanggal (YYYY-MM-DD)"),
        tanggal_selesai: date | None = Query(None, description="Batas akhir tanggal (YYYY-MM-DD)"),
        db: Session = Depends(get_db), scope: str | None = Depends(get_cabang_scope)):
    """Exploratory Data Analysis: ringkasan dataset, kelengkapan data, statistik deskriptif,
    tren bulanan, pola hari, efek kalender (akhir pekan/libur) dan distribusi kategori.
    Semua role yang login boleh mengakses; Kepala Outlet otomatis dibatasi ke cabangnya."""
    if tanggal_mulai and tanggal_selesai and tanggal_mulai > tanggal_selesai:
        raise HTTPException(status_code=400, detail="Tanggal mulai tidak boleh setelah tanggal selesai.")
    return svc.analisis_eda(db, cabang=scope, tanggal_mulai=tanggal_mulai, tanggal_selesai=tanggal_selesai)
