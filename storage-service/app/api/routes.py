from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse
from app.deps.auth import get_actor
from app.db.session import get_db
from app.services.storage import service
from sqlalchemy.orm import Session

router = APIRouter(prefix="/storage")


@router.get("/health", tags=["Storage"])
def health():
    return {"status": "ok", "service": "storage-service"}


@router.post("/upload", tags=["Storage"])
async def upload(module: str, category: str, file: UploadFile = File(...), actor=Depends(get_actor), db: Session = Depends(get_db)):
    return {"message": "File uploaded successfully", "data": await service.upload(db=db, actor=actor, module=module, category=category, file=file)}


@router.get("/files/{object_key:path}", tags=["Storage"])
def read_file(object_key: str, db: Session = Depends(get_db)):
    response = service.get(db=db, object_key=object_key)
    headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/auth/profile-pictures/" in f"/{object_key}" or "/auth/company-logos/" in f"/{object_key}" else {}
    return StreamingResponse(response.stream(32 * 1024), media_type=response.headers.get("Content-Type"), headers=headers)


@router.get("/download-file/{object_key:path}", tags=["Storage"])
def download_file(object_key: str, actor=Depends(get_actor), db: Session = Depends(get_db)):
    response = service.download(db=db, actor=actor, object_key=object_key)
    return StreamingResponse(response.stream(32 * 1024), media_type=response.headers.get("Content-Type"))


@router.get("/file-info/{object_key:path}", tags=["Storage"])
def file_info(object_key: str, actor=Depends(get_actor), db: Session = Depends(get_db)):
    return {"message": "File details loaded", "data": service.info(db=db, actor=actor, object_key=object_key)}


@router.delete("/files/{object_key:path}", tags=["Storage"])
def delete_file(object_key: str, actor=Depends(get_actor), db: Session = Depends(get_db)):
    service.delete(db=db, actor=actor, object_key=object_key)
    return {"message": "File deleted successfully"}


@router.get("/download-url", tags=["Storage"])
def download_url(object_key: str, actor=Depends(get_actor), db: Session = Depends(get_db)):
    return {"message": "Download URL generated", "data": {"url": service.presigned_download(db=db, actor=actor, object_key=object_key)}}
