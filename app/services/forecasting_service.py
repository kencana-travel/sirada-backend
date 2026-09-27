"""
Service Forecasting Demand per Rute.
Menggunakan Holt-Winters Exponential Smoothing (statsmodels) - alternatif yang lebih ringan
dari ARIMA/Prophet, tetap menangkap tren & musiman mingguan, sesuai rancangan algoritma (P.4 pada DFD).
"""
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from sqlalchemy.orm import Session
from app.models.models import Transaksi, Rute


def _ambil_deret_harian(db: Session, nama_rute: str) -> pd.Series:
    rows = (db.query(Transaksi.tanggal, Transaksi.jumlah_unit)
              .join(Rute, Rute.id_rute == Transaksi.id_rute)
              .filter(Rute.nama_rute == nama_rute, Transaksi.jenis_transaksi == "Penumpang")
              .all())
    df = pd.DataFrame(rows, columns=["tanggal", "jumlah_unit"])
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    harian = df.groupby("tanggal")["jumlah_unit"].sum().asfreq("D").fillna(0)
    return harian


def jalankan_forecast(db: Session, nama_rute: str, horizon_hari: int = 30):
    harian = _ambil_deret_harian(db, nama_rute)
    if len(harian) < 30:
        raise ValueError("Data historis rute ini belum cukup untuk forecasting (minimal 30 hari).")

    # --- Evaluasi akurasi: train/test split 14 hari terakhir ---
    test_size = min(14, len(harian) // 5)
    train, test = harian.iloc[:-test_size], harian.iloc[-test_size:]
    model_eval = ExponentialSmoothing(train, trend="add", seasonal="add", seasonal_periods=7,
                                       initialization_method="estimated").fit()
    pred_test = model_eval.forecast(test_size)
    mape = float(np.mean(np.abs((test.values - pred_test.values) / np.where(test.values == 0, 1, test.values))) * 100)
    akurasi = max(0.0, 100 - mape)

    # --- Model final pakai seluruh data, forecast ke depan ---
    model_final = ExponentialSmoothing(harian, trend="add", seasonal="add", seasonal_periods=7,
                                        initialization_method="estimated").fit()
    forecast = model_final.forecast(horizon_hari)
    forecast = forecast.clip(lower=0)

    # Ambil 30 hari terakhir aktual untuk ditampilkan berdampingan dengan proyeksi (kurva di UI)
    aktual_tampil = harian.iloc[-30:]

    deret = []
    for tgl, val in aktual_tampil.items():
        deret.append({"tanggal": tgl.date(), "aktual": round(float(val), 1), "prediksi": None})
    for tgl, val in forecast.items():
        deret.append({"tanggal": tgl.date(), "aktual": None, "prediksi": round(float(val), 1)})

    prediksi_periode = float(forecast.sum())
    rata_kapasitas_harian = float(harian.mean()) if harian.mean() > 0 else 1
    rekomendasi_unit = max(0, int(round((forecast.mean() - harian.mean()) / max(rata_kapasitas_harian, 1) * 2)))

    return {
        "rute": nama_rute,
        "prediksi_periode_berikutnya": round(prediksi_periode, 0),
        "akurasi_persen": round(akurasi, 1),
        "mape_persen": round(mape, 1),
        "rekomendasi_unit_tambahan": rekomendasi_unit,
        "deret": deret,
    }
