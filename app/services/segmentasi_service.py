"""
Service Segmentasi Pasar: RFM (Recency, Frequency, Monetary) + K-Means Clustering.
Sesuai algoritma yang sudah disepakati di rancangan (P.3 pada DFD).
"""
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import Transaksi, Rute, Member


def ringkasan_per_member(db: Session):
    """Sesuai 3 kartu di UI Segmentasi: total transaksi/pendapatan/rata-rata/rute favorit per jenis member."""
    q = (db.query(Member.jenis_member,
                   func.count(Transaksi.id_transaksi).label("total_transaksi"),
                   func.sum(Transaksi.total_bayar).label("total_pendapatan"))
           .join(Transaksi, Transaksi.id_member == Member.id_member)
           .filter(Transaksi.jenis_transaksi == "Penumpang")
           .group_by(Member.jenis_member).all())

    grand_total = sum(r.total_transaksi for r in q) or 1
    hasil = []
    for r in q:
        # rute favorit per member type
        rute_fav = (db.query(Rute.nama_rute, func.count(Transaksi.id_transaksi).label("n"))
                      .join(Transaksi, Transaksi.id_rute == Rute.id_rute)
                      .join(Member, Member.id_member == Transaksi.id_member)
                      .filter(Member.jenis_member == r.jenis_member)
                      .group_by(Rute.nama_rute).order_by(func.count(Transaksi.id_transaksi).desc())
                      .first())
        hasil.append({
            "jenis_member": r.jenis_member,
            "total_transaksi": r.total_transaksi,
            "total_pendapatan": float(r.total_pendapatan or 0),
            "rata_rata_transaksi": float((r.total_pendapatan or 0) / r.total_transaksi),
            "rute_favorit": rute_fav.nama_rute if rute_fav else "-",
            "share_persen": round(100 * r.total_transaksi / grand_total, 1),
        })
    return sorted(hasil, key=lambda x: -x["total_transaksi"])


def jalankan_rfm_kmeans(db: Session, n_clusters: int = 4, limit_pelanggan: int = 5000):
    """Hitung RFM per pelanggan (nama_pelanggan dipakai sbg proxy ID pelanggan pada dataset ini),
    lalu klaster pakai K-Means. Mengembalikan (ringkasan_cluster, tabel_pelanggan)."""
    rows = (db.query(Transaksi.nama_pelanggan, Transaksi.tanggal, Transaksi.total_bayar)
              .filter(Transaksi.jenis_transaksi == "Penumpang", Transaksi.nama_pelanggan.isnot(None))
              .all())
    df = pd.DataFrame(rows, columns=["nama_pelanggan", "tanggal", "total_bayar"])
    if df.empty:
        return [], []

    ref_date = df["tanggal"].max()
    rfm = df.groupby("nama_pelanggan").agg(
        recency_hari=("tanggal", lambda s: (ref_date - s.max()).days),
        frequency=("total_bayar", "count"),
        monetary=("total_bayar", "sum"),
    ).reset_index()

    X = rfm[["recency_hari", "frequency", "monetary"]].copy()
    X_scaled = StandardScaler().fit_transform(X)

    k = min(n_clusters, max(2, len(rfm) // 5)) if len(rfm) >= 8 else 2
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    rfm["cluster"] = km.fit_predict(X_scaled)

    # Beri label tier berdasar ranking monetary rata-rata tiap cluster (tinggi -> Platinum)
    urutan = rfm.groupby("cluster")["monetary"].mean().sort_values(ascending=False).index.tolist()
    label_tier = ["Tier Platinum", "Tier Gold", "Tier Silver", "Calon Member"]
    label_map = {cl: label_tier[i] if i < len(label_tier) else f"Tier {i+1}"
                 for i, cl in enumerate(urutan)}
    rfm["label"] = rfm["cluster"].map(label_map)

    ringkasan = []
    for cl in urutan:
        sub = rfm[rfm["cluster"] == cl]
        ringkasan.append({
            "cluster": int(cl),
            "label": label_map[cl],
            "jumlah_pelanggan": int(len(sub)),
            "rata_recency_hari": round(float(sub["recency_hari"].mean()), 1),
            "rata_frequency": round(float(sub["frequency"].mean()), 1),
            "rata_monetary": round(float(sub["monetary"].mean()), 0),
        })

    tabel = (rfm.sort_values("monetary", ascending=False)
                .head(limit_pelanggan)
                [["nama_pelanggan", "frequency", "monetary", "label"]]
                .rename(columns={"frequency": "total_transaksi", "monetary": "total_belanja",
                                  "label": "status_loyalitas"})
                .to_dict(orient="records"))
    return ringkasan, tabel
