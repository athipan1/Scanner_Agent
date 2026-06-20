from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    TRADING_MODE: str = "PAPER"
    SCANNER_DEV_MODE: bool = False

    @field_validator("TRADING_MODE")
    @classmethod
    def validate_trading_mode(cls, value: str) -> str:
        mode = str(value or "PAPER").upper()
        if mode not in {"PAPER", "LIVE"}:
            raise ValueError("TRADING_MODE must be PAPER or LIVE")
        return mode

    # Scoring weights
    QUALITY_SCORE_WEIGHT: float = 0.40
    GROWTH_SCORE_WEIGHT: float = 0.35
    VALUATION_SCORE_WEIGHT: float = 0.25

    # Alpaca API
    APCA_API_KEY_ID: str = "YOUR_API_KEY"
    APCA_API_SECRET_KEY: str = "YOUR_SECRET_KEY"
    APCA_API_BASE_URL: str = "https://paper-api.alpaca.markets"

    DEFAULT_SYMBOLS: list[str] = [
        "PTT", "AOT", "DELTA", "CPALL", "BBL", "SCB", "KBANK", "GULF",
        "ADVANC", "SCC", "BDMS", "PTTEP", "EA", "CPN", "TRUE", "HMPRO",
        "INTUCH", "MINT", "CRC", "OR"
    ]


settings = Settings()
