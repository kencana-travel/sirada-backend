from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.models.models import Pengguna, Rute
from app.services import forecasting_service as svc
from app.schemas.schemas import ForecastingRunRequest

router = APIRouter(prefix="/api/forecasting", tags=["Forecasting Demand"])


@router.get("/rute-tersedia")
def rute_tersedia(db: Session = Depends(get_db), _user: Pengguna = Depends(get_current_user)):
    """Untuk dropdown 'Koridor Perjalanan' di UI Forecasting."""
    return [r.nama_rute for r in db.query(Rute).all()]


@router.post("/run")
def run(payload: ForecastingRunRequest, db: Session = Depends(get_db),
        _user: Pengguna = Depends(require_roles("Admin"))):
    """Sesuai tombol 'Jalankan Model AI' - jalankan ARIMA untuk 1 rute."""
    try:
        return svc.jalankan_forecast(db, payload.rute, payload.horizon_hari)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
