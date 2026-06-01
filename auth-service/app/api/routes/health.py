from fastapi import APIRouter

router = APIRouter(tags=['Health'])


@router.get('/health')
def health():
    return {'message': 'Service healthy', 'data': {'status': 'ok'}}
