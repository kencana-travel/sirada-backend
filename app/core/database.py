"""Koneksi database. Default: SQLite file lokal (kencana.db).
Untuk produksi tinggal ganti DATABASE_URL ke PostgreSQL, tidak ada kode lain yang berubah
karena semua akses lewat SQLAlchemy ORM."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./kencana.db")
# Beberapa penyedia (termasuk Railway versi lama) memakai skema "postgres://",
# yang tidak dikenali SQLAlchemy 2.x.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
# pool_pre_ping: buang koneksi Postgres yang sudah diputus server sebelum dipakai.
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
