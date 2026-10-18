from fastapi import APIRouter

from app.api.v1 import auth, me, methodology, products, scans

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(scans.router)
api_router.include_router(products.router)
api_router.include_router(methodology.router)
api_router.include_router(me.router)
