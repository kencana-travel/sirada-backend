"""
Service Analisis Performa Rute & Cabang - statistik deskriptif + load factor.
Sesuai rancangan algoritma (P.5 pada DFD).
"""
import pandas as pd
from sqlalchemy.orm import Session
from app.models.models import Transaksi, Rute, Armada


def analisis_performa_rute(db: Session):
    rows = (db.query(Rute.nama_rute, Transaksi.jenis_transaksi, Transaksi.jumlah_unit,
                      Transaksi.total_bayar, Transaksi.layanan, Transaksi.tanggal,
                      Transaksi.jam_keberangkatan, Armada.kapasitas)
              .join(Rute, Rute.id_rute == Transaksi.id_rute)
              .outerjoin(Armada, Armada.id_armada == Transaksi.id_armada)
              .all())
    df = pd.DataFrame(rows, columns=["rute", "jenis_transaksi", "jumlah_unit", "total_bayar",
                                      "layanan", "tanggal", "jam_keberangkatan", "kapasitas"])
    penumpang = df[df["jenis_transaksi"] == "Penumpang"].copy()

    hasil = []
    for rute, grp in penumpang.groupby("rute"):
        total_trip = grp.drop_duplicates(subset=["tanggal", "jam_keberangkatan"]).shape[0]
        total_transaksi = len(grp)
        total_penumpang = int(grp["jumlah_unit"].sum())
        total_pendapatan = float(grp["total_bayar"].sum())
        kapasitas_per_trip = grp["kapasitas"].mean() if grp["kapasitas"].notna().any() else 10
        kapasitas_tersedia = int(total_trip * kapasitas_per_trip)
        okupansi = round(100 * total_penumpang / kapasitas_tersedia, 1) if kapasitas_tersedia else 0
        layanan_dominan = grp["layanan"].mode().iloc[0] if not grp["layanan"].mode().empty else "-"
        hasil.append({
            "rute": rute, "total_trip": total_trip, "total_transaksi": total_transaksi,
            "total_penumpang": total_penumpang, "total_pendapatan": total_pendapatan,
            "kapasitas_tersedia": kapasitas_tersedia, "okupansi_persen": okupansi,
            "layanan_dominan": layanan_dominan,
        })
    hasil.sort(key=lambda x: -x["total_pendapatan"])
    return hasil


def perbandingan_vip_reguler(db: Session):
    rows = (db.query(Transaksi.layanan, Transaksi.total_bayar, Transaksi.harga_satuan)
              .filter(Transaksi.jenis_transaksi == "Penumpang").all())
    df = pd.DataFrame(rows, columns=["layanan", "total_bayar", "harga_satuan"])
    total = len(df)
    hasil = []
    for layanan, grp in df.groupby("layanan"):
        hasil.append({
            "layanan": layanan,
            "share_persen": round(100 * len(grp) / total, 1),
            "rata_harga_tiket": round(float(grp["harga_satuan"].mean()), 0),
            "total_pendapatan": float(grp["total_bayar"].sum()),
        })
    return hasil
