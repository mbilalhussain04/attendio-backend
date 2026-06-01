from fastapi import HTTPException


def bad_request(message: str):
    raise HTTPException(status_code=400, detail=message)


def unauthorized(message: str = 'Unauthorized'):
    raise HTTPException(status_code=401, detail=message)


def forbidden(message: str = 'Forbidden'):
    raise HTTPException(status_code=403, detail=message)


def not_found(message: str = 'Not found'):
    raise HTTPException(status_code=404, detail=message)


def conflict(message: str = 'Conflict'):
    raise HTTPException(status_code=409, detail=message)
