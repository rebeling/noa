from fastapi import APIRouter

from app.api.v1.endpoints import auth, views, voice

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(voice.router, prefix="/voice", tags=["voice"])
api_router.include_router(views.router, tags=["views"])
