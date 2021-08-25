from fastapi import APIRouter
from fastapi.responses import JSONResponse


router = APIRouter()


@router.get("", include_in_schema=False)
def healthcheck():
    data = {
        'health': 'OK',
        'message': 'Everything is ok',
        'details': None
    }
    return JSONResponse(data)
