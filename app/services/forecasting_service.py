"""
Service Forecasting Demand per Rute: perbandingan beberapa model deret waktu, lalu dipilih
model dengan MAPE terkecil pada data uji. Sesuai rancangan algoritma (P.4 pada DFD) dan
BAB II subbab 2.8:
  1. deret harian jumlah penumpang per rute (hanya transaksi 'Penumpang', hari kosong = 0)
  2. uji stasioneritas ADF -> menentukan d (differencing maks. 2 kali)
  3. kandidat model:
       - ARIMA(p,d,q)          : p dan q dipilih dari grid 0-2 dengan AIC
       - SARIMA(p,d,q)(P,D,Q,7): musiman mingguan, grid kecil (P,Q) dipilih dengan AIC
       - SARIMAX               : SARIMA + variabel eksogen dari tabel kalender
                                 (akhir pekan, libur nasional, H-1/H+1 libur nasional,
                                 libur sekolah)
       - Holt-Winters aditif   : tren teredam + musiman mingguan
  4. evaluasi pada data uji (28 hari terakhir) dengan MAE, RMSE, MAPE; pemenang = MAPE terkecil
     (diagnostic checking: uji Ljung-Box lag 14 pada residual model terpilih)
  5. model pemenang dilatih ulang pada seluruh data latih lalu forecast ke depan
  6. MAPE diklasifikasikan menurut Lewis (1982)
"""
import copy
import itertools
import math
import threading
import time
import warnings
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import adfuller

from app.models.models import Armada, Kalender, Rute, Transaksi

ALPHA_ADF = 0.05
MAKS_DIFFERENCING = 2
KANDIDAT_P = range(0, 3)
KANDIDAT_Q = range(0, 3)

MUSIM = 7  # musiman mingguan (data harian)
# Grid SARIMA sengaja kecil supaya cepat: ordo non-musiman (1,d,1), D=1, dan (P,Q) dipilih AIC.
KANDIDAT_MUSIMAN_PQ = [(0, 1), (1, 1)]
MAKS_ITERASI = 50  # batas iterasi optimizer state-space (cukup untuk konvergen pada data ini)

# Data uji = 28 hari terakhir (4 siklus mingguan penuh). 28 hari dipilih daripada 14 karena
# memuat lebih banyak hari libur/akhir pekan, jadi MAPE lebih mewakili kondisi sebenarnya.
HARI_UJI = 28
# Jendela latih dibatasi 730 hari terakhir (2 tahun) agar satu kali run tetap ~10-30 detik
# (Railway lebih lambat). Dua tahun tetap memuat dua siklus libur nasional & libur sekolah.
JENDELA_LATIH_HARI = 730
MIN_HARI_DATA = 60
HARI_TAMPIL_AKTUAL = 30

# Kapasitas: rata-rata perjalanan/hari dan kapasitas armada dihitung dari 90 hari terakhir.
JENDELA_KAPASITAS_HARI = 90
TARGET_LOAD_FACTOR = 0.80
KAPASITAS_DEFAULT = 10  # bila armada transaksi tidak tercatat

MAPE_MAKS_VALID = 20.0
KOLOM_EKSOGEN = ["weekend", "libur_nasional", "sekitar_libur", "libur_sekolah"]

NAMA_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

# Cache hasil di memori: key = (rute, horizon, pakai_kalender, tanggal maks, jumlah baris).
# Data baru (tanggal maks / jumlah baris berubah) otomatis membuat key baru.
_CACHE: dict[tuple, dict] = {}
_CACHE_MAKS = 64
_CACHE_LOCK = threading.Lock()


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
def _signature_rute(db: Session, nama_rute: str):
    return (db.query(func.max(Transaksi.tanggal), func.count(Transaksi.id_transaksi))
              .join(Rute, Rute.id_rute == Transaksi.id_rute)
              .filter(Rute.nama_rute == nama_rute, Transaksi.jenis_transaksi == "Penumpang")
              .one())


def _ambil_deret_harian(db: Session, nama_rute: str, tanggal_maks) -> pd.Series:
    mulai = tanggal_maks - timedelta(days=JENDELA_LATIH_HARI - 1)
    rows = (db.query(Transaksi.tanggal, func.sum(Transaksi.jumlah_unit))
              .join(Rute, Rute.id_rute == Transaksi.id_rute)
              .filter(Rute.nama_rute == nama_rute,
                      Transaksi.jenis_transaksi == "Penumpang",
                      Transaksi.tanggal >= mulai)
              .group_by(Transaksi.tanggal)
              .all())
    df = pd.DataFrame(rows, columns=["tanggal", "jumlah_unit"])
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    df["jumlah_unit"] = df["jumlah_unit"].astype(float)
    harian = df.groupby("tanggal")["jumlah_unit"].sum().asfreq("D").fillna(0.0)
    return harian


def _ambil_kalender(db: Session, mulai, selesai) -> pd.DataFrame:
    """Variabel eksogen per tanggal. Tanggal yang belum ada di tabel kalender diisi 0,
    kecuali 'weekend' yang bisa diturunkan langsung dari nama hari."""
    rows = (db.query(Kalender.tanggal, Kalender.weekend, Kalender.libur_nasional,
                     Kalender.libur_sekolah)
              .filter(Kalender.tanggal >= mulai - timedelta(days=1),
                      Kalender.tanggal <= selesai + timedelta(days=1))
              .all())
    idx = pd.date_range(mulai - timedelta(days=1), selesai + timedelta(days=1), freq="D")
    kal = pd.DataFrame(rows, columns=["tanggal", "weekend", "libur_nasional", "libur_sekolah"])
    kal["tanggal"] = pd.to_datetime(kal["tanggal"])
    kal = kal.set_index("tanggal").reindex(idx)
    kal["weekend"] = kal["weekend"].fillna(pd.Series(idx.dayofweek >= 5, index=idx))
    kal = kal.fillna(False).astype(float)
    # Lonjakan penumpang di data terjadi H-1 s.d. H+1 libur nasional (arus mudik/balik),
    # jadi hari di sekitar libur nasional dijadikan dummy tersendiri.
    ln = kal["libur_nasional"]
    sekitar = (ln.shift(1, fill_value=0) + ln.shift(-1, fill_value=0)) > 0
    kal["sekitar_libur"] = (sekitar & (ln == 0)).astype(float)
    return kal.loc[pd.Timestamp(mulai):pd.Timestamp(selesai), KOLOM_EKSOGEN]


def _kapasitas_rute(db: Session, nama_rute: str, tanggal_maks) -> dict:
    """Rata-rata perjalanan per hari (kombinasi jam keberangkatan + layanan + armada) dan
    rata-rata kapasitas armada pada rute ini, 90 hari terakhir."""
    mulai = tanggal_maks - timedelta(days=JENDELA_KAPASITAS_HARI - 1)
    rows = (db.query(Transaksi.tanggal, Transaksi.jam_keberangkatan, Transaksi.layanan,
                     Transaksi.id_armada, func.max(Armada.kapasitas))
              .join(Rute, Rute.id_rute == Transaksi.id_rute)
              .outerjoin(Armada, Armada.id_armada == Transaksi.id_armada)
              .filter(Rute.nama_rute == nama_rute,
                      Transaksi.jenis_transaksi == "Penumpang",
                      Transaksi.tanggal >= mulai)
              .group_by(Transaksi.tanggal, Transaksi.jam_keberangkatan, Transaksi.layanan,
                        Transaksi.id_armada)
              .all())
    if not rows:
        return {"perjalanan_per_hari": 0.0, "kapasitas_per_perjalanan": float(KAPASITAS_DEFAULT),
                "kursi_per_hari": 0.0}
    df = pd.DataFrame(rows, columns=["tanggal", "jam", "layanan", "armada", "kapasitas"])
    jumlah_hari = df["tanggal"].nunique()
    perjalanan = len(df) / max(jumlah_hari, 1)
    kap = df["kapasitas"].dropna()
    kap_rata = float(kap.mean()) if len(kap) else float(KAPASITAS_DEFAULT)
    return {"perjalanan_per_hari": perjalanan, "kapasitas_per_perjalanan": kap_rata,
            "kursi_per_hari": perjalanan * kap_rata}


# --------------------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------------------
def _tentukan_d(deret: pd.Series) -> tuple[int, float]:
    """Uji ADF berulang: H0 = deret punya unit root (tidak stasioner).
    Jika p-value >= 0.05, deret di-differencing lalu diuji ulang."""
    y = deret.astype(float)
    p_value = 1.0
    for d in range(MAKS_DIFFERENCING + 1):
        if y.nunique() <= 1:  # deret konstan, ADF tidak bisa dihitung
            return d, 0.0
        p_value = float(adfuller(y, autolag="AIC")[1])
        if p_value < ALPHA_ADF or d == MAKS_DIFFERENCING:
            return d, p_value
        y = y.diff().dropna()
    return MAKS_DIFFERENCING, p_value


def _diam(fn):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # ConvergenceWarning/ValueWarning dari statsmodels
        return fn()


def _fit_arima(deret, order):
    return _diam(lambda: ARIMA(deret, order=order).fit())


def _fit_sarimax(deret, order, seasonal, exog=None):
    return _diam(lambda: SARIMAX(deret, exog=exog, order=order, seasonal_order=seasonal,
                                 enforce_stationarity=False, enforce_invertibility=False)
                 .fit(disp=False, maxiter=MAKS_ITERASI))


def _fit_hw(deret):
    return _diam(lambda: ExponentialSmoothing(deret, trend="add", damped_trend=True,
                                              seasonal="add", seasonal_periods=MUSIM).fit())


def _pilih_ordo(deret: pd.Series, d: int):
    """Bandingkan kandidat ARIMA(p, d, q) dan ambil AIC terkecil. Mengembalikan juga
    model terbaik supaya tidak perlu fit ulang untuk forecast data uji."""
    terbaik, aic_terbaik, model_terbaik = (1, d, 0), np.inf, None
    for p, q in itertools.product(KANDIDAT_P, KANDIDAT_Q):
        try:
            model = _fit_arima(deret, (p, d, q))
        except Exception:
            continue
        if np.isfinite(model.aic) and model.aic < aic_terbaik:
            terbaik, aic_terbaik, model_terbaik = (p, d, q), model.aic, model
    return terbaik, model_terbaik


def _pilih_musiman(deret: pd.Series, d: int, exog=None):
    terbaik, aic_terbaik, model_terbaik = None, np.inf, None
    for P, Q in KANDIDAT_MUSIMAN_PQ:
        seasonal = (P, 1, Q, MUSIM)
        try:
            model = _fit_sarimax(deret, (1, d, 1), seasonal, exog)
        except Exception:
            continue
        if np.isfinite(model.aic) and model.aic < aic_terbaik:
            terbaik, aic_terbaik, model_terbaik = seasonal, model.aic, model
    return terbaik, model_terbaik


def _metrik(aktual: np.ndarray, prediksi: np.ndarray) -> dict:
    galat = aktual - prediksi
    mae = float(np.mean(np.abs(galat)))
    rmse = float(np.sqrt(np.mean(galat ** 2)))
    # MAPE tidak terdefinisi saat aktual = 0, jadi hari tanpa penumpang dikeluarkan.
    nonzero = aktual != 0
    mape = float(np.mean(np.abs(galat[nonzero] / aktual[nonzero])) * 100) if nonzero.any() else 0.0
    return {"mae": mae, "rmse": rmse, "mape": mape}


LAG_LJUNG_BOX = 14  # dua siklus mingguan
ALPHA_LJUNG_BOX = 0.05


def _uji_residual(model) -> dict | None:
    """Diagnostic checking: uji Ljung-Box pada residual model terpilih.
    H0 = residual tidak berautokorelasi (white noise). p-value > 0,05 berarti H0 tidak ditolak,
    sehingga pola data dianggap sudah tertangkap model. Residual awal (masa pemanasan
    differencing/musiman) dibuang agar tidak mendistorsi uji."""
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        resid = pd.Series(np.asarray(model.resid, dtype=float)).iloc[2 * MUSIM:]
        resid = resid[np.isfinite(resid)]
        if len(resid) <= LAG_LJUNG_BOX * 2:
            return None
        p_value = float(acorr_ljungbox(resid, lags=[LAG_LJUNG_BOX], return_df=True)["lb_pvalue"].iloc[0])
        return {"metode": "Ljung-Box", "lag": LAG_LJUNG_BOX, "p_value": round(p_value, 4),
                "lolos": bool(p_value > ALPHA_LJUNG_BOX)}
    except Exception:
        return None


def kategori_mape(mape: float) -> str:
    """Klasifikasi akurasi peramalan menurut Lewis (1982)."""
    if mape < 10:
        return "Sangat baik"
    if mape <= 20:
        return "Baik"
    if mape <= 50:
        return "Layak"
    return "Buruk"


def _bandingkan_model(train, test, exog_train, exog_test, d):
    """Latih tiap kandidat pada data latih, hitung metrik pada data uji.
    Hasil: list dict {nama, metrik, refit(deret, exog) -> model, pakai_exog}."""
    h = len(test)
    aktual = test.values.astype(float)
    kandidat = []

    def catat(nama, prediksi, refit, pakai_exog=False):
        pred = np.clip(np.asarray(prediksi, dtype=float), 0, None)
        if not np.all(np.isfinite(pred)):
            return
        kandidat.append({"nama": nama, "metrik": _metrik(aktual, pred), "refit": refit,
                         "pakai_exog": pakai_exog})

    # 1) ARIMA(p,d,q) dengan grid AIC
    try:
        order, model = _pilih_ordo(train, d)
        if model is not None:
            catat(f"ARIMA({order[0]},{order[1]},{order[2]})", model.forecast(h),
                  lambda y, X, o=order: _fit_arima(y, o))
    except Exception:
        pass

    # 2) SARIMA mingguan
    seasonal = None
    try:
        seasonal, model = _pilih_musiman(train, d)
        if model is not None:
            P, D, Q, s = seasonal
            catat(f"SARIMA(1,{d},1)({P},{D},{Q},{s})", model.forecast(h),
                  lambda y, X, sz=seasonal: _fit_sarimax(y, (1, d, 1), sz))
    except Exception:
        pass

    # 3) SARIMAX = SARIMA + dummy kalender (pakai ordo musiman pemenang AIC SARIMA)
    if exog_train is not None:
        kolom = [c for c in exog_train.columns if exog_train[c].nunique() > 1]
        if kolom:
            sx = seasonal or (0, 1, 1, MUSIM)
            try:
                model = _fit_sarimax(train, (1, d, 1), sx, exog_train[kolom])
                P, D, Q, s = sx
                catat(f"SARIMAX(1,{d},1)({P},{D},{Q},{s})+kalender",
                      model.forecast(h, exog=exog_test[kolom]),
                      lambda y, X, sz=sx, k=kolom: _fit_sarimax(y, (1, d, 1), sz, X[k]),
                      pakai_exog=kolom)
            except Exception:
                pass

    # 4) Holt-Winters aditif
    try:
        model = _fit_hw(train)
        catat("Holt-Winters aditif (s=7)", model.forecast(h), lambda y, X: _fit_hw(y))
    except Exception:
        pass

    return kandidat


# --------------------------------------------------------------------------------------
# Rekomendasi
# --------------------------------------------------------------------------------------
def _rekomendasi(forecast: pd.Series, kapasitas: dict) -> dict:
    puncak_tgl = forecast.idxmax()
    puncak = float(forecast.max())
    rata = float(forecast.mean())
    kursi = kapasitas["kursi_per_hari"]
    kap_perjalanan = max(kapasitas["kapasitas_per_perjalanan"], 1.0)
    perjalanan_now = kapasitas["perjalanan_per_hari"]

    # Perjalanan yang dibutuhkan agar load factor hari puncak tidak melebihi 80%.
    butuh = math.ceil(puncak / (kap_perjalanan * TARGET_LOAD_FACTOR)) if puncak > 0 else 0
    tambahan = max(0, butuh - math.floor(perjalanan_now + 1e-9))
    hari_tambahan = int((forecast > kursi * TARGET_LOAD_FACTOR).sum()) if kursi > 0 else 0

    # Hari tersibuk menurut rata-rata prediksi per nama hari.
    per_hari = forecast.groupby(forecast.index.dayofweek).mean().sort_values(ascending=False)
    sibuk = [NAMA_HARI[i] for i in per_hari.index[:2]]

    lf_puncak = puncak / kursi * 100 if kursi > 0 else 0.0
    lf_rata = rata / kursi * 100 if kursi > 0 else 0.0
    catatan = (f"Permintaan tertinggi diperkirakan pada hari {' dan '.join(sibuk)}; "
               f"puncak {puncak:.0f} pax pada {puncak_tgl.strftime('%d-%m-%Y')} "
               f"(load factor {lf_puncak:.0f}% dari {kursi:.0f} kursi/hari). ")
    if tambahan > 0:
        catatan += (f"Tambahkan {tambahan} perjalanan/unit pada {hari_tambahan} hari "
                    f"dengan prediksi di atas {TARGET_LOAD_FACTOR:.0%} kapasitas.")
    else:
        catatan += "Kapasitas jadwal saat ini mencukupi, tidak perlu unit tambahan."

    return {
        "rekomendasi_unit_tambahan": int(tambahan),
        "catatan_jadwal": catatan,
        "kapasitas": {
            "perjalanan_per_hari": round(perjalanan_now, 1),
            "kapasitas_per_perjalanan": round(kap_perjalanan, 1),
            "kursi_per_hari": round(kursi, 0),
            "target_load_factor_persen": round(TARGET_LOAD_FACTOR * 100, 0),
            "prediksi_puncak_harian": round(puncak, 0),
            "tanggal_puncak": puncak_tgl.date(),
            "prediksi_rata_harian": round(rata, 1),
            "load_factor_puncak_persen": round(lf_puncak, 1),
            "load_factor_rata_persen": round(lf_rata, 1),
            "hari_perlu_tambahan": hari_tambahan,
        },
    }


# --------------------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------------------
def jalankan_forecast(db: Session, nama_rute: str, horizon_hari: int = 30,
                      pakai_kalender: bool = True) -> dict:
    tanggal_maks, jumlah_baris = _signature_rute(db, nama_rute)
    if tanggal_maks is None:
        raise ValueError(f"Tidak ada data penumpang untuk rute '{nama_rute}'.")
    if isinstance(tanggal_maks, str):  # jaga-jaga driver mengembalikan string
        tanggal_maks = pd.Timestamp(tanggal_maks).date()

    key = (nama_rute, int(horizon_hari), bool(pakai_kalender), str(tanggal_maks), int(jumlah_baris))
    with _CACHE_LOCK:
        if key in _CACHE:
            hasil = copy.deepcopy(_CACHE[key])
            hasil["dari_cache"] = True
            return hasil

    mulai_waktu = time.perf_counter()
    harian = _ambil_deret_harian(db, nama_rute, tanggal_maks)
    if len(harian) < MIN_HARI_DATA:
        raise ValueError(f"Data historis rute ini belum cukup untuk forecasting "
                         f"(minimal {MIN_HARI_DATA} hari).")

    idx_depan = pd.date_range(harian.index[-1] + pd.Timedelta(days=1), periods=horizon_hari,
                              freq="D")
    exog_all = exog_depan = None
    if pakai_kalender:
        kal = _ambil_kalender(db, harian.index[0].date(), idx_depan[-1].date())
        exog_all, exog_depan = kal.loc[harian.index], kal.loc[idx_depan]

    # --- Evaluasi akurasi: train/test split 28 hari terakhir ---
    test_size = min(HARI_UJI, len(harian) // 5)
    train, test = harian.iloc[:-test_size], harian.iloc[-test_size:]
    d, adf_p_value = _tentukan_d(train)
    exog_train = exog_all.iloc[:-test_size] if exog_all is not None else None
    exog_test = exog_all.iloc[-test_size:] if exog_all is not None else None

    kandidat = _bandingkan_model(train, test, exog_train, exog_test, d)
    if not kandidat:
        raise ValueError("Semua model gagal dilatih untuk rute ini.")
    pemenang = min(kandidat, key=lambda k: k["metrik"]["mape"])

    # --- Model pemenang dilatih ulang pada seluruh data, lalu forecast ke depan ---
    model_final = pemenang["refit"](harian, exog_all)
    if pemenang["pakai_exog"]:
        forecast = model_final.forecast(horizon_hari, exog=exog_depan[pemenang["pakai_exog"]])
    else:
        forecast = model_final.forecast(horizon_hari)
    forecast = pd.Series(np.clip(np.asarray(forecast, dtype=float), 0, None), index=idx_depan)

    metrik = pemenang["metrik"]
    mape = metrik["mape"]
    akurasi = max(0.0, 100 - mape)

    deret = []
    for tgl, val in harian.iloc[-HARI_TAMPIL_AKTUAL:].items():
        deret.append({"tanggal": tgl.date(), "aktual": round(float(val), 1), "prediksi": None})
    for tgl, val in forecast.items():
        deret.append({"tanggal": tgl.date(), "aktual": None, "prediksi": round(float(val), 1)})

    perbandingan = [{
        "model": k["nama"],
        "mae": round(k["metrik"]["mae"], 2),
        "rmse": round(k["metrik"]["rmse"], 2),
        "mape_persen": round(k["metrik"]["mape"], 2),
        "kategori_mape": kategori_mape(k["metrik"]["mape"]),
        "terpilih": k is pemenang,
    } for k in sorted(kandidat, key=lambda k: k["metrik"]["mape"])]

    rek = _rekomendasi(forecast, _kapasitas_rute(db, nama_rute, tanggal_maks))

    hasil = {
        "rute": nama_rute,
        "model": pemenang["nama"],
        "adf_p_value": round(adf_p_value, 4),
        "ordo_differencing": d,
        "prediksi_periode_berikutnya": round(float(forecast.sum()), 0),
        "horizon_hari": int(horizon_hari),
        "akurasi_persen": round(akurasi, 1),
        "mape_persen": round(mape, 2),
        "mae": round(metrik["mae"], 2),
        "rmse": round(metrik["rmse"], 2),
        "kategori_mape": kategori_mape(mape),
        "valid": bool(mape <= MAPE_MAKS_VALID),
        "mape_maks_valid": MAPE_MAKS_VALID,
        "perbandingan": perbandingan,
        "pakai_kalender": bool(pakai_kalender),
        "variabel_eksogen": pemenang["pakai_exog"] or [],
        "hari_uji": int(test_size),
        "jendela_latih_hari": int(len(harian)),
        "periode_data": {"mulai": harian.index[0].date(), "selesai": harian.index[-1].date()},
        "rekomendasi_unit_tambahan": rek["rekomendasi_unit_tambahan"],
        "catatan_jadwal": rek["catatan_jadwal"],
        "kapasitas": rek["kapasitas"],
        "uji_residual": _uji_residual(model_final),
        "deret": deret,
        "durasi_detik": round(time.perf_counter() - mulai_waktu, 1),
        "dari_cache": False,
    }

    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAKS:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = copy.deepcopy(hasil)
    return hasil
