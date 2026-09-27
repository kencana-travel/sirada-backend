"""Migrasi ringan saat startup (proyek ini belum memakai Alembic).

- Membuat tabel baru yang belum ada (mis. token_pengguna).
- Menambah kolom baru di tabel pengguna pada database lama. Akun lama otomatis
  dianggap sudah terverifikasi & aktif lewat server_default kolomnya.
Aman dijalankan berulang kali."""
import logging
from sqlalchemy import inspect, text
from app.core.database import Base, engine
from app.models import models  # noqa: F401  (registrasi semua model ke Base.metadata)

log = logging.getLogger(__name__)

KOLOM_PENGGUNA_BARU = {
    "email_terverifikasi": "BOOLEAN NOT NULL DEFAULT '1'",
    "status": "VARCHAR NOT NULL DEFAULT 'aktif'",
    "dibuat_pada": "TIMESTAMP",
}


def jalankan_migrasi():
    Base.metadata.create_all(bind=engine)

    kolom_ada = {c["name"] for c in inspect(engine).get_columns("pengguna")}
    with engine.begin() as conn:
        for nama, definisi in KOLOM_PENGGUNA_BARU.items():
            if nama not in kolom_ada:
                conn.execute(text(f"ALTER TABLE pengguna ADD COLUMN {nama} {definisi}"))
                log.info("Migrasi: kolom pengguna.%s ditambahkan", nama)
