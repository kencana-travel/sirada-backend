"""
Model tabel sesuai ERD & Class Diagram yang sudah disusun sebelumnya:
Cabang, Rute, Armada, Jadwal, Member, JenisPaket, Transaksi, Pengguna (akun login).
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Date, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime, timezone
import uuid


def gen_id():
    return uuid.uuid4().hex[:12]


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Pengguna(Base):
    """Akun login sistem (Admin, Owner, Kepala Outlet) - untuk kebutuhan auth,
    terpisah dari entitas bisnis di ERD."""
    __tablename__ = "pengguna"
    id_pengguna = Column(String, primary_key=True, default=gen_id)
    nama = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    # Admin | Owner | KepalaOutlet. Kosong ("") untuk pendaftar yang belum disetujui Admin.
    role = Column(String, nullable=False)
    id_cabang = Column(String, ForeignKey("cabang.id_cabang"), nullable=True)  # khusus KepalaOutlet
    email_terverifikasi = Column(Boolean, nullable=False, default=False, server_default="1")
    # menunggu (daftar sendiri, belum di-approve) | aktif | ditolak
    status = Column(String, nullable=False, default="menunggu", server_default="aktif")
    dibuat_pada = Column(DateTime, nullable=True, default=utcnow)


class TokenPengguna(Base):
    """Token sekali pakai untuk link di email. Yang disimpan hanya hash SHA-256-nya,
    jadi isi database yang bocor tidak bisa dipakai untuk verifikasi/reset."""
    __tablename__ = "token_pengguna"
    id_token = Column(String, primary_key=True, default=gen_id)
    id_pengguna = Column(String, ForeignKey("pengguna.id_pengguna"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    jenis = Column(String, nullable=False)  # verifikasi_email | reset_password
    kedaluwarsa = Column(DateTime, nullable=False)
    dipakai_pada = Column(DateTime, nullable=True)
    dibuat_pada = Column(DateTime, nullable=False, default=utcnow)


class Cabang(Base):
    __tablename__ = "cabang"
    id_cabang = Column(String, primary_key=True, default=gen_id)
    nama_cabang = Column(String, unique=True, nullable=False)
    kota = Column(String, nullable=False)


class Rute(Base):
    __tablename__ = "rute"
    id_rute = Column(String, primary_key=True, default=gen_id)
    nama_rute = Column(String, unique=True, nullable=False)  # e.g. "Solo->Semarang"
    cabang_asal = Column(String, ForeignKey("cabang.nama_cabang"), nullable=False)
    cabang_tujuan = Column(String, nullable=False)
    layanan_tersedia = Column(String, nullable=False)  # "VIP" / "Reguler" / "VIP,Reguler"


class Armada(Base):
    __tablename__ = "armada"
    id_armada = Column(String, primary_key=True, default=gen_id)
    kode_armada = Column(String, unique=True, nullable=False)
    jenis_kendaraan = Column(String, nullable=False)
    tipe_layanan = Column(String, nullable=False)
    kapasitas = Column(Integer, nullable=False)
    basis_outlet = Column(String, ForeignKey("cabang.nama_cabang"), nullable=True)


class Jadwal(Base):
    __tablename__ = "jadwal"
    id_jadwal = Column(String, primary_key=True, default=gen_id)
    id_rute = Column(String, ForeignKey("rute.id_rute"), nullable=False)
    jam_keberangkatan = Column(String, nullable=False)
    layanan = Column(String, nullable=False)
    hari_berlaku = Column(String, default="Setiap Hari")


class Member(Base):
    __tablename__ = "member"
    id_member = Column(String, primary_key=True, default=gen_id)
    jenis_member = Column(String, unique=True, nullable=False)  # Non-Member/Member Umum/Member Mahasiswa
    diskon_per_tiket = Column(Float, default=0)


class JenisPaket(Base):
    __tablename__ = "jenis_paket"
    id_jenis_paket = Column(String, primary_key=True, default=gen_id)
    nama_paket = Column(String, unique=True, nullable=False)  # Reguler / Elektronik
    tarif_5kg_pertama = Column(Float, nullable=False)
    tarif_per_kg_lanjut = Column(Float, nullable=False)


class Transaksi(Base):
    __tablename__ = "transaksi"
    # Index hanya di kolom yang selektif (PK, tanggal, id_rute). Kolom seperti layanan/channel
    # hanya punya 2-3 nilai, jadi index-nya tidak dipakai query tapi memakan belasan MB per
    # index dan memperbesar WAL saat bulk insert (volume Postgres trial Railway hanya ~0,5 GB).
    id_transaksi = Column(String, primary_key=True)   # kode booking (KCN-xxxxx / SLOxxxxxx dst)
    tanggal = Column(Date, nullable=False, index=True)
    hari = Column(String)
    jam_keberangkatan = Column(String, nullable=False)
    id_rute = Column(String, ForeignKey("rute.id_rute"), nullable=False, index=True)
    id_armada = Column(String, ForeignKey("armada.id_armada"), nullable=True)
    cabang_asal = Column(String, nullable=False)
    cabang_tujuan = Column(String, nullable=False)
    layanan = Column(String, nullable=False)
    jenis_transaksi = Column(String, nullable=False)  # Penumpang / Paket
    id_member = Column(String, ForeignKey("member.id_member"), nullable=True)
    id_jenis_paket = Column(String, ForeignKey("jenis_paket.id_jenis_paket"), nullable=True)
    jumlah_unit = Column(Float, nullable=False)  # jml orang ATAU berat kg
    satuan = Column(String, nullable=False)
    channel_pemesanan = Column(String, nullable=False)
    harga_satuan = Column(Float, nullable=False)
    diskon_per_tiket = Column(Float, default=0)
    total_harga = Column(Float, nullable=False)
    total_diskon = Column(Float, default=0)
    total_bayar = Column(Float, nullable=False)
    keterangan = Column(String)
    nama_pelanggan = Column(String, nullable=True)  # opsional, untuk tampilan "Data Transaksi"

    rute = relationship("Rute")
    armada = relationship("Armada")
    member = relationship("Member")
    jenis_paket_rel = relationship("JenisPaket")
