from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.models import Pengguna

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Pengguna:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token tidak valid atau kedaluwarsa",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    email = payload.get("sub")
    user = db.query(Pengguna).filter(Pengguna.email == email).first()
    # Token lama tidak berlaku lagi bila akun sudah ditolak/dinonaktifkan Admin.
    if user is None or user.status != "aktif":
        raise credentials_exception
    return user


def require_roles(*roles):
    """Dependency factory: batasi endpoint hanya untuk role tertentu.
    Contoh: Depends(require_roles('Admin'))"""
    def checker(user: Pengguna = Depends(get_current_user)) -> Pengguna:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Tidak punya akses untuk aksi ini")
        return user
    return checker
