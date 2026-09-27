from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.models import Transaksi, Rute, Member, Pengguna

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), _user: Pengguna = Depends(get_current_user)):
    """4 kartu atas: Total Transaksi, Total Pendapatan, Rute Terlaris, Rasio Member/Non."""
    total_transaksi = db.query(func.count(Transaksi.id_transaksi)).scalar() or 0
    total_pendapatan = db.query(func.sum(Transaksi.total_bayar)).scalar() or 0

    rute_terlaris = (db.query(Rute.nama_rute, func.sum(Transaksi.jumlah_unit).label("pnp"))
                        .join(Transaksi, Transaksi.id_rute == Rute.id_rute)
                        .filter(Transaksi.jenis_transaksi == "Penumpang")
                        .group_by(Rute.nama_rute).order_by(func.sum(Transaksi.jumlah_unit).desc())
                        .first())

    total_member = (db.query(func.count(Transaksi.id_transaksi))
                       .join(Member, Member.id_member == Transaksi.id_member)
                       .filter(Transaksi.jenis_transaksi == "Penumpang",
                               Member.jenis_member != "Non-Member").scalar() or 0)
    total_penumpang_tx = (db.query(func.count(Transaksi.id_transaksi))
                             .filter(Transaksi.jenis_transaksi == "Penumpang").scalar() or 1)
    total_non_member = total_penumpang_tx - total_member
    grand = max(total_penumpang_tx, 1)

    return {
        "total_transaksi": total_transaksi,
        "total_pendapatan": float(total_pendapatan),
        "rute_terlaris": rute_terlaris.nama_rute if rute_terlaris else "-",
        "penumpang_rute_terlaris": int(rute_terlaris.pnp) if rute_terlaris else 0,
        "rasio_member_persen": round(100 * total_member / grand, 1),
        "rasio_non_member_persen": round(100 * total_non_member / grand, 1),
    }


@router.get("/distribusi-member")
def distribusi_member(db: Session = Depends(get_db), _user: Pengguna = Depends(get_current_user)):
    """Donut chart 'Segmentasi Pelanggan' di Dashboard."""
    rows = (db.query(Member.jenis_member, func.count(Transaksi.id_transaksi).label("jumlah"))
              .join(Transaksi, Transaksi.id_member == Member.id_member)
              .filter(Transaksi.jenis_transaksi == "Penumpang")
              .group_by(Member.jenis_member).all())
    total = sum(r.jumlah for r in rows) or 1
    return [{"jenis_member": r.jenis_member, "jumlah": r.jumlah,
             "persen": round(100 * r.jumlah / total, 1)} for r in rows]


@router.get("/aktivitas-terkini")
def aktivitas_terkini(limit: int = 5, db: Session = Depends(get_db),
                       _user: Pengguna = Depends(get_current_user)):
    """Tabel 'Aktivitas Transaksi Terkini' di bagian bawah Dashboard."""
    rows = (db.query(Transaksi.id_transaksi, Transaksi.nama_pelanggan, Rute.nama_rute,
                      Transaksi.jam_keberangkatan, Transaksi.total_bayar, Member.jenis_member)
              .join(Rute, Rute.id_rute == Transaksi.id_rute)
              .outerjoin(Member, Member.id_member == Transaksi.id_member)
              .order_by(Transaksi.tanggal.desc(), Transaksi.jam_keberangkatan.desc())
              .limit(limit).all())
    return [dict(r._mapping) for r in rows]
