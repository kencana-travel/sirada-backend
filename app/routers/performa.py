from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Pengguna
from app.services import performa_service as svc

router = APIRouter(prefix="/api/performa-rute", tags=["Performa Rute"])


@router.get("")
def performa(db: Session = Depends(get_db), _user: Pengguna = Depends(get_current_user)):
    """Tabel 'Detail Performa 6 Rute Utama' + distribusi volume di UI Performa Rute."""
    return svc.analisis_performa_rute(db)


@router.get("/vip-vs-reguler")
def vip_vs_reguler(db: Session = Depends(get_db), _user: Pengguna = Depends(get_current_user)):
    """Sesuai kartu 'Perbandingan Layanan VIP vs Reguler' di UI."""
    return svc.perbandingan_vip_reguler(db)
