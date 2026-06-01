from io import BytesIO
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from uuid import UUID
from uuid import uuid4
from fastapi import HTTPException, UploadFile
from minio import Minio
from minio.error import S3Error
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.integrations.events import publish_event
from app.models.stored_object import StoredObject

ALLOWED_TARGETS = {
    ("auth", "profile-pictures"): {"image/jpeg", "image/jpg", "image/png", "image/webp"},
    ("auth", "company-logos"): {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/svg+xml"},
    ("leave", "attachments"): {"application/pdf", "image/jpeg", "image/png"},
    ("payroll", "documents"): {"application/pdf"},
}


class StorageService:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.local_root = Path(settings.LOCAL_STORAGE_DIR).expanduser().resolve()

    def _use_local_backend(self) -> bool:
        if settings.STORAGE_BACKEND.lower() == "local":
            return True
        if settings.STORAGE_BACKEND.lower() == "minio":
            return False
        try:
            self.ensure_bucket()
            return False
        except Exception:
            return True

    def ensure_bucket(self):
        if not self.client.bucket_exists(settings.MINIO_BUCKET):
            self.client.make_bucket(settings.MINIO_BUCKET)

    @staticmethod
    def _safe_filename(filename: str | None, extension: str) -> str:
        source = PurePosixPath(filename or f"attachment{extension}").name
        stem = PurePosixPath(source).stem or "attachment"
        cleaned_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("._-") or "attachment"
        return f"{cleaned_stem[:120]}{extension}"

    def _object_key(self, *, actor: dict, module: str, category: str, filename: str | None, extension: str) -> str:
        if (module, category) == ("leave", "attachments"):
            uploaded_at = datetime.now(timezone.utc)
            safe_name = PurePosixPath(self._safe_filename(filename, extension))
            display_filename = f"{safe_name.stem}-{uploaded_at:%Y-%m-%d-%H%M%S}{safe_name.suffix}"
            return (
                f"companies/{actor['company_id']}/employees/{actor['sub']}/leave/attachments/"
                f"{uploaded_at:%Y/%m}/{uuid4().hex}/{display_filename}"
            )
        return f"{actor['company_id']}/{module}/{category}/{actor['sub']}/{uuid4().hex}{extension}"

    async def upload(self, *, db: Session, actor: dict, module: str, category: str, file: UploadFile) -> dict:
        allowed_types = ALLOWED_TARGETS.get((module, category))
        if not allowed_types:
            raise HTTPException(status_code=400, detail="Unsupported storage target")
        is_auth_image = module == "auth" and category in {"profile-pictures", "company-logos"}
        if not is_auth_image and file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail="Unsupported file type")
        if is_auth_image and not (file.content_type or "").startswith("image/"):
            raise HTTPException(status_code=400, detail="Unsupported file type")
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="File is empty")
        if len(raw) > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File is too large")
        extension = PurePosixPath(file.filename or "").suffix.lower() or {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "application/pdf": ".pdf",
        }.get(file.content_type, "")
        content_type = file.content_type
        if (module, category) == ("auth", "profile-pictures"):
            try:
                image = Image.open(BytesIO(raw))
                image.load()
                image = ImageOps.exif_transpose(image).convert("RGB")
                image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS)
                buffer = BytesIO()
                image.save(buffer, format="WEBP", quality=88)
                raw = buffer.getvalue()
                extension = ".webp"
                content_type = "image/webp"
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Invalid profile image") from exc
        object_key = self._object_key(
            actor=actor,
            module=module,
            category=category,
            filename=file.filename,
            extension=extension,
        )
        if self._use_local_backend():
            target = self.local_root / object_key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        else:
            try:
                self.client.put_object(settings.MINIO_BUCKET, object_key, BytesIO(raw), len(raw), content_type=content_type)
            except S3Error as exc:
                raise HTTPException(status_code=503, detail="Object storage unavailable") from exc
        stored = StoredObject(
            company_id=UUID(actor["company_id"]),
            owner_user_id=UUID(actor["sub"]),
            module=module,
            category=category,
            object_key=object_key,
            original_filename=file.filename,
            content_type=content_type,
            size_bytes=len(raw),
            checksum_sha256=sha256(raw).hexdigest(),
            visibility="public" if module == "auth" and category in {"profile-pictures", "company-logos"} else "private",
            metadata_json={},
        )
        db.add(stored)
        db.commit()
        db.refresh(stored)
        publish_event(
            "storage.file.uploaded",
            actor["company_id"],
            {
                "file_id": str(stored.id),
                "object_key": object_key,
                "module": module,
                "category": category,
                "owner_user_id": actor["sub"],
                "visibility": stored.visibility,
            },
        )
        return {
            "id": str(stored.id),
            "object_key": object_key,
            "url": f"{settings.PUBLIC_STORAGE_BASE_URL.rstrip('/')}/{object_key}",
            "content_type": content_type,
            "size": len(raw),
            "module": module,
            "category": category,
            "original_filename": file.filename,
        }

    def _object_response(self, *, object_key: str, stored: StoredObject):
        if self._use_local_backend():
            target = self.local_root / object_key
            if not target.exists():
                raise HTTPException(status_code=404, detail="File not found")
            return LocalObjectResponse(target, stored.content_type)
        try:
            return self.client.get_object(settings.MINIO_BUCKET, object_key)
        except S3Error as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc

    def get(self, *, db: Session, object_key: str):
        stored = db.scalar(select(StoredObject).where(StoredObject.object_key == object_key, StoredObject.status == "active"))
        if not stored:
            raise HTTPException(status_code=404, detail="File not found")
        if stored.visibility != "public":
            raise HTTPException(status_code=403, detail="Public access is not allowed for this file")
        return self._object_response(object_key=object_key, stored=stored)

    def download(self, *, db: Session, actor: dict, object_key: str):
        stored = db.scalar(select(StoredObject).where(StoredObject.object_key == object_key, StoredObject.status == "active"))
        if not stored:
            raise HTTPException(status_code=404, detail="File not found")
        if str(stored.company_id) != actor["company_id"]:
            raise HTTPException(status_code=403, detail="Cross tenant file access denied")
        return self._object_response(object_key=object_key, stored=stored)

    def info(self, *, db: Session, actor: dict, object_key: str) -> dict:
        stored = db.scalar(select(StoredObject).where(StoredObject.object_key == object_key, StoredObject.status == "active"))
        if not stored:
            raise HTTPException(status_code=404, detail="File not found")
        if str(stored.company_id) != actor["company_id"]:
            raise HTTPException(status_code=403, detail="Cross tenant file access denied")
        return {
            "object_key": stored.object_key,
            "original_filename": stored.original_filename,
            "created_at": stored.created_at.isoformat() if stored.created_at else None,
        }

    def delete(self, *, db: Session, actor: dict, object_key: str):
        stored = db.scalar(select(StoredObject).where(StoredObject.object_key == object_key, StoredObject.status == "active"))
        if not stored:
            raise HTTPException(status_code=404, detail="File not found")
        if str(stored.company_id) != actor["company_id"] or str(stored.owner_user_id) != actor["sub"]:
            raise HTTPException(status_code=403, detail="Cannot delete another user's file")
        if self._use_local_backend():
            target = self.local_root / object_key
            if target.exists():
                target.unlink()
        else:
            try:
                self.client.remove_object(settings.MINIO_BUCKET, object_key)
            except S3Error as exc:
                raise HTTPException(status_code=503, detail="Object storage unavailable") from exc
        stored.status = "deleted"
        stored.deleted_at = datetime.now(timezone.utc)
        db.add(stored)
        db.commit()
        publish_event(
            "storage.file.deleted",
            actor["company_id"],
            {"file_id": str(stored.id), "object_key": object_key, "owner_user_id": actor["sub"]},
        )

    def presigned_download(self, *, db: Session, actor: dict, object_key: str) -> str:
        stored = db.scalar(select(StoredObject).where(StoredObject.object_key == object_key, StoredObject.status == "active"))
        if not stored:
            raise HTTPException(status_code=404, detail="File not found")
        if str(stored.company_id) != actor["company_id"]:
            raise HTTPException(status_code=403, detail="Cross tenant file access denied")
        if self._use_local_backend():
            return f"{settings.PUBLIC_STORAGE_BASE_URL.rstrip('/')}/{object_key}"
        try:
            return self.client.presigned_get_object(settings.MINIO_BUCKET, object_key)
        except S3Error as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc


class LocalObjectResponse:
    def __init__(self, path: Path, content_type: str):
        self.path = path
        self.headers = {"Content-Type": content_type}

    def stream(self, chunk_size: int):
        with self.path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk


service = StorageService()
