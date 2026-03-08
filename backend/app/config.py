from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "US RealView API"
    cors_origins: str = "http://localhost:3000"
    refresh_interval_seconds: int = 60
    replay_retention_hours: int = 24
    use_live_feeds: bool = True

    default_lat: float = 32.7767
    default_lon: float = -96.7970
    nws_user_agent: str = "USRealView/1.0 (local demo)"
    dallas_traffic_url: str = "https://www.dallasopendata.com/resource/tqs9-xfzb.json?$limit=200"
    dallas_incidents_url: str = "https://www.dallasopendata.com/resource/qv6i-rri7.json?$limit=200&$where=geocoded_column%20IS%20NOT%20NULL&$order=reporteddate%20DESC"
    dallas_crimes_url: str = "https://www.dallasopendata.com/resource/pumt-d92b.json?$limit=200&$order=offensedate%20DESC"

    @property
    def cors_origins_list(self):
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
