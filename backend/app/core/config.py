import json
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "GeoPortal"
    API_V1_STR: str = "/api/v1"

    # Database configuration supporting both GEOPORTAL_DB_* and POSTGRES_* environment variables
    POSTGRES_SERVER: str = os.getenv("GEOPORTAL_DB_HOST", os.getenv("POSTGRES_SERVER", "localhost"))
    POSTGRES_PORT: int = int(os.getenv("GEOPORTAL_DB_PORT", os.getenv("POSTGRES_PORT", "5432")))
    POSTGRES_USER: str = os.getenv("GEOPORTAL_DB_USER", os.getenv("POSTGRES_USER", "postgres"))
    POSTGRES_PASSWORD: str = os.getenv("GEOPORTAL_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "postgres"))
    POSTGRES_DB: str = os.getenv("GEOPORTAL_DB_NAME", os.getenv("POSTGRES_DB", "Taqnen_data"))
    ADMIN_DEFAULT_DATABASE: str = os.getenv("ADMIN_DEFAULT_DATABASE", "postgres")

    # Statutory Egyptian Feddan conversion constant
    FEDDAN_CONSTANT: float = 4200.8333

    # Default GeoPackage source dataset path
    DEFAULT_GPKG_PATH: str = os.getenv("GPKG_PATH", r"d:\Systems\MapViewer\Unified_Database.gpkg")

    # Security and JWT settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "geoportal_super_secret_jwt_key_2026_production_grade")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def ADMIN_DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.ADMIN_DEFAULT_DATABASE}"
        )

    @property
    def RAW_DB_PARAMS(self) -> dict:
        return {
            "host": self.POSTGRES_SERVER,
            "port": self.POSTGRES_PORT,
            "user": self.POSTGRES_USER,
            "password": self.POSTGRES_PASSWORD,
            "dbname": self.POSTGRES_DB,
        }

    class Config:
        case_sensitive = True
        extra = "allow"


settings = Settings()

# Optional file-based override (written by the admin-only connection API).
# Lets the admin change the Postgres connection at runtime without env vars
# or restarts; applied on top of environment configuration at startup.
DB_CONNECTION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "db_connection.json"
)
_DB_KEYS = ("POSTGRES_SERVER", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")


def load_connection_file() -> dict:
    try:
        with open(DB_CONNECTION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {k: data[k] for k in _DB_KEYS if k in data and data[k] not in (None, "")}
    except Exception:
        return {}


def save_connection_file(values: dict) -> dict:
    cleaned = {}
    for k in _DB_KEYS:
        if k in values and values[k] not in (None, ""):
            cleaned[k] = int(values[k]) if k == "POSTGRES_PORT" else str(values[k])
    merged = load_connection_file()
    merged.update(cleaned)
    with open(DB_CONNECTION_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged


def apply_connection_file() -> dict:
    applied = load_connection_file()
    for k, v in applied.items():
        setattr(settings, k, v)
    return applied


apply_connection_file()
