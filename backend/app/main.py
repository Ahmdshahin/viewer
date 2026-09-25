import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api import auth, layers, upload, analysis, users, processor, point_processor, migrate, dbadmin, export, tiles, search, features, prefs, update_geometry

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(layers.router, prefix=f"{settings.API_V1_STR}/layers", tags=["layers"])
app.include_router(tiles.router, prefix=f"{settings.API_V1_STR}/layers", tags=["tiles"])
app.include_router(upload.router, prefix=f"{settings.API_V1_STR}/upload", tags=["upload"])
app.include_router(analysis.router, prefix=f"{settings.API_V1_STR}/analysis", tags=["analysis"])
app.include_router(users.router, prefix=f"{settings.API_V1_STR}/users", tags=["users"])
app.include_router(processor.router, prefix=f"{settings.API_V1_STR}/processor", tags=["processor"])
app.include_router(point_processor.router, prefix=f"{settings.API_V1_STR}/point", tags=["point"])
app.include_router(migrate.router, prefix=f"{settings.API_V1_STR}/processor/migrate", tags=["migrate"])
app.include_router(dbadmin.router, prefix=f"{settings.API_V1_STR}/admin/db", tags=["db-admin"])
app.include_router(export.router, prefix=f"{settings.API_V1_STR}/export", tags=["export"])
app.include_router(search.router, prefix=f"{settings.API_V1_STR}/search", tags=["search"])
app.include_router(features.router, prefix=f"{settings.API_V1_STR}/features", tags=["features"])
app.include_router(prefs.router, prefix=f"{settings.API_V1_STR}/prefs", tags=["prefs"])
app.include_router(update_geometry.router, prefix=f"{settings.API_V1_STR}/update", tags=["update"])

@app.get("/")
def root():
    index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.isdir(FRONTEND_DIST) and os.path.isfile(index):
        return FileResponse(index)
    return {"message": "Welcome to GeoPortal API"}


# ---- Single-port production serving ----
# When frontend/dist exists (npm run build), serve the built app from the
# same backend port so the server needs only one open port + no dev server.
FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "dist"
)
if os.path.isdir(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        candidate = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
