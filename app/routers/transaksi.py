import io
import csv
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.core.deps import get_current_user, require_roles
from app.models.models import Transaksi, Rute, Member, Pengguna
from app.schemas.schemas import TransaksiListOut, TransaksiOut, TransaksiCreate

router = APIRouter(prefix="/api/transaksi", tags=["Data Transaksi"])


def _base_query(db: Session):
    return db.query(
        Transaksi.id_transaksi, Transaksi.tanggal, Transaksi.jam_keberangkatan,
        Rute.nama_rute.label("rute"), Transaksi.layanan, Transaksi.channel_pemesanan,
        Member.jenis_member.label("jenis_member"), Transaksi.jumlah_unit,
        Transaksi.satuan, Transaksi.total_bayar, Transaksi.keterangan,
    ).join(Rute, Rute.id_rute == Transaksi.id_rute
    ).outerjoin(Member, Member.id_member == Transaksi.id_member)


@router.get("", response_model=TransaksiListOut)
def list_transaksi(
    db: Session = Depends(get_db),
    _user: Pengguna = Depends(get_current_user),
    cari: Optional[str] = Query(None, description="Cari kode transaksi / nama pelanggan"),
    rute: Optional[str] = Query(None),
    layanan: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    tanggal_mulai: Optional[date] = Query(None),
    tanggal_selesai: Optional[date] = Query(None),
    halaman: int = Query(1, ge=1),
    per_halaman: int = Query(10, ge=1, le=200),
):
    """Sesuai UI 'Data Transaksi Pemesanan Tiket': search box, filter Rute/Layanan/Channel, pagination."""
    q = _base_query(db)
    if cari:
        like = f"%{cari}%"
        q = q.filter(Transaksi.id_transaksi.ilike(like) | Transaksi.nama_pelanggan.ilike(like))
    if rute:
        q = q.filter(Rute.nama_rute == rute)
    if layanan:
        q = q.filter(Transaksi.layanan == layanan)
    if channel:
        q = q.filter(Transaksi.channel_pemesanan == channel)
    if tanggal_mulai:
        q = q.filter(Transaksi.tanggal >= tanggal_mulai)
    if tanggal_selesai:
        q = q.filter(Transaksi.tanggal <= tanggal_selesai)

    total = q.order_by(None).count()
    rows = (q.order_by(Transaksi.tanggal.desc(), Transaksi.jam_keberangkatan.desc())
             .offset((halaman - 1) * per_halaman).limit(per_halaman).all())
    data = [TransaksiOut(**row._mapping) for row in rows]
    return TransaksiListOut(total=total, halaman=halaman, per_halaman=per_halaman, data=data)


@router.post("", response_model=TransaksiOut)
def tambah_transaksi(payload: TransaksiCreate, db: Session = Depends(get_db),
                      user: Pengguna = Depends(require_roles("Admin"))):
    """Sesuai tombol 'Tambah Transaksi' di UI."""
    rute = db.query(Rute).filter(Rute.nama_rute == payload.rute).first()
    if not rute:
        asal, tujuan = payload.rute.split("->")
        rute = Rute(nama_rute=payload.rute, cabang_asal=asal, cabang_tujuan=tujuan,
                    layanan_tersedia=payload.layanan)
        db.add(rute)
        db.flush()

    member = db.query(Member).filter(Member.jenis_member == payload.jenis_member).first()
    diskon = member.diskon_per_tiket if member else 0
    harga_dasar = 105000  # ASUMSI default; idealnya diambil dari tabel tarif per rute+layanan
    total_harga = harga_dasar * payload.jumlah_unit
    total_diskon = diskon * payload.jumlah_unit

    import uuid
    kode = f"KCN{uuid.uuid4().hex[:8].upper()}"
    trx = Transaksi(
        id_transaksi=kode, tanggal=payload.tanggal, hari=payload.tanggal.strftime("%A"),
        jam_keberangkatan=payload.jam_keberangkatan, id_rute=rute.id_rute,
        cabang_asal=rute.cabang_asal, cabang_tujuan=rute.cabang_tujuan,
        layanan=payload.layanan, jenis_transaksi=payload.jenis_transaksi,
        id_member=member.id_member if member else None,
        jumlah_unit=payload.jumlah_unit, satuan=payload.satuan,
        channel_pemesanan=payload.channel_pemesanan, harga_satuan=harga_dasar,
        diskon_per_tiket=diskon, total_harga=total_harga, total_diskon=total_diskon,
        total_bayar=total_harga - total_diskon, keterangan="Input Manual",
        nama_pelanggan=payload.nama_pelanggan,
    )
    db.add(trx)
    db.commit()
    row = _base_query(db).filter(Transaksi.id_transaksi == kode).first()
    return TransaksiOut(**row._mapping)


@router.get("/export")
def export_csv(db: Session = Depends(get_db), _user: Pengguna = Depends(get_current_user)):
    """Sesuai tombol 'Export Laporan PDF' / 'Import CSV' di UI (versi CSV export)."""
    rows = _base_query(db).order_by(Transaksi.tanggal.desc()).limit(50000).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Kode Transaksi", "Tanggal", "Jam", "Rute", "Layanan", "Channel",
                      "Jenis Member", "Jumlah Unit", "Satuan", "Total Bayar", "Keterangan"])
    for r in rows:
        writer.writerow(list(r._mapping.values()))
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=transaksi_export.csv"})
