"""
Service Forecasting Demand per Rute dengan ARIMA(p, d, q) (statsmodels).
Sesuai rancangan algoritma (P.4 pada DFD) dan BAB II subbab 2.8:
  1. deret harian jumlah penumpang per rute
  2. uji stasioneritas ADF -> menentukan d (differencing maks. 2 kali)
  3. identifikasi p dan q: kandidat ARIMA dibandingkan dengan AIC
  4. evaluasi pada data uji (14 hari terakhir) dengan MAE, RMSE, MAPE
  5. model final dilatih ulang pada seluruh data lalu forecast ke depan
"""
import itertools
import warnings

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller

from app.models.models import Transaksi, Rute

ALPHA_ADF = 0.05
MAKS_DIFFERENCING = 2
KANDIDAT_P = range(0, 3)
KANDIDAT_Q = range(0, 3)


def _ambil_deret_harian(db: Session, nama_rute: str) -> pd.Series:
    rows = (db.query(Transaksi.tanggal, Transaksi.jumlah_unit)
              .join(Rute, Rute.id_rute == Transaksi.id_rute)
              .filter(Rute.nama_rute == nama_rute, Transaksi.jenis_transaksi == "Penumpang")
              .all())
    df = pd.DataFrame(rows, columns=["tanggal", "jumlah_unit"])
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    harian = df.groupby("tanggal")["jumlah_unit"].sum().asfreq("D").fillna(0)
    return harian


def _tentukan_d(deret: pd.Series) -> tuple[int, float]:
    """Uji ADF berulang: H0 = deret punya unit root (tidak stasioner).
    Jika p-value >= 0.05, deret di-differencing lalu diuji ulang."""
    y = deret.astype(float)
    for d in range(MAKS_DIFFERENCING + 1):
        if y.nunique() <= 1:  # deret konstan, ADF tidak bisa dihitung
            return d, 0.0
        p_value = float(adfuller(y, autolag="AIC")[1])
        if p_value < ALPHA_ADF or d == MAKS_DIFFERENCING:
            return d, p_value
        y = y.diff().dropna()
    return MAKS_DIFFERENCING, p_value


def _fit(deret: pd.Series, order: tuple[int, int, int]):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # ConvergenceWarning/ValueWarning dari statsmodels
        return ARIMA(deret, order=order).fit()


def _pilih_ordo(deret: pd.Series, d: int) -> tuple[int, int, int]:
    """Bandingkan kandidat ARIMA(p, d, q) dan ambil AIC terkecil."""
    terbaik, aic_terbaik = (1, d, 0), np.inf
    for p, q in itertools.product(KANDIDAT_P, KANDIDAT_Q):
        try:
            aic = _fit(deret, (p, d, q)).aic
        except Exception:
            continue
        if np.isfinite(aic) and aic < aic_terbaik:
            terbaik, aic_terbaik = (p, d, q), aic
    return terbaik


def _metrik(aktual: np.ndarray, prediksi: np.ndarray) -> dict:
    galat = aktual - prediksi
    mae = float(np.mean(np.abs(galat)))
    rmse = float(np.sqrt(np.mean(galat ** 2)))
    # MAPE tidak terdefinisi saat aktual = 0, jadi hari tanpa penumpang dikeluarkan.
    nonzero = aktual != 0
    mape = float(np.mean(np.abs(galat[nonzero] / aktual[nonzero])) * 100) if nonzero.any() else 0.0
    return {"mae": mae, "rmse": rmse, "mape": mape}


def jalankan_forecast(db: Session, nama_rute: str, horizon_hari: int = 30):
    harian = _ambil_deret_harian(db, nama_rute)
    if len(harian) < 30:
        raise ValueError("Data historis rute ini belum cukup untuk forecasting (minimal 30 hari).")

    # --- Evaluasi akurasi: train/test split 14 hari terakhir ---
    test_size = min(14, len(harian) // 5)
    train, test = harian.iloc[:-test_size], harian.iloc[-test_size:]
    d, adf_p_value = _tentukan_d(train)
    order = _pilih_ordo(train, d)
    pred_test = _fit(train, order).forecast(test_size).clip(lower=0)
    metrik = _metrik(test.values.astype(float), pred_test.values)
    akurasi = max(0.0, 100 - metrik["mape"])

    # --- Model final pakai seluruh data dengan ordo yang sama, forecast ke depan ---
    forecast = _fit(harian, order).forecast(horizon_hari).clip(lower=0)

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

    p, d, q = order
    return {
        "rute": nama_rute,
        "model": f"ARIMA({p},{d},{q})",
        "adf_p_value": round(adf_p_value, 4),
        "prediksi_periode_berikutnya": round(prediksi_periode, 0),
        "akurasi_persen": round(akurasi, 1),
        "mape_persen": round(metrik["mape"], 2),
        "mae": round(metrik["mae"], 2),
        "rmse": round(metrik["rmse"], 2),
        "rekomendasi_unit_tambahan": rekomendasi_unit,
        "deret": deret,
    }
