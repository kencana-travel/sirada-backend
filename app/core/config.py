"""Konfigurasi email & URL frontend, dibaca dari environment variable."""
import os

# API key Resend (https://resend.com/api-keys). Kosong = mode dev: email tidak dikirim,
# isi & link-nya dicetak ke log server supaya alur tetap bisa dites.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

# Alamat pengirim. onboarding@resend.dev hanya bisa mengirim ke email pemilik akun Resend;
# untuk mengirim ke siapa pun, verifikasi domain di Resend lalu ganti ke no-reply@domainanda.
MAIL_FROM = os.getenv("MAIL_FROM", "SIRADA Kencana <onboarding@resend.dev>")

# Dipakai untuk membangun link di dalam email (verifikasi & reset password).
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

VERIFIKASI_EMAIL_EXPIRE_JAM = 24
RESET_PASSWORD_EXPIRE_MENIT = 30

# Syarat minimal jumlah baris transaksi sebelum analisis boleh dijalankan (flowchart:
# "data lengkap & jumlah >= 100.000 baris").
MIN_BARIS_ANALISIS = int(os.getenv("MIN_BARIS_ANALISIS", "100000"))
