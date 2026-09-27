from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.models.models import Pengguna
from app.services import segmentasi_service as svc

router = APIRouter(prefix="/api/segmentasi", tags=["Segmentasi Pasar"])


@router.get("/ringkasan")
def ringkasan(db: Session = Depends(get_db), _user: Pengguna = Depends(get_current_user)):
    """3 kartu ringkasan per Jenis Member (Mahasiswa/Umum/Non-Member) - sesuai UI Segmentasi."""
    return svc.ringkasan_per_member(db)


@router.get("/cluster")
def cluster(n_cluster: int = Query(4, ge=2, le=8),
            db: Session = Depends(get_db), _user: Pengguna = Depends(require_roles("Admin"))):
    """Jalankan RFM + K-Means, kembalikan ringkasan tiap cluster + tabel pelanggan (Status Loyalitas)."""
    ringkasan_cluster, tabel_pelanggan = svc.jalankan_rfm_kmeans(db, n_clusters=n_cluster)
    return {"ringkasan_cluster": ringkasan_cluster, "pelanggan": tabel_pelanggan}
