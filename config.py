
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

class Config:
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "library-local-testing-secret-key-123456789"
    )

    SQLALCHEMY_DATABASE_URI = (
        "sqlite:///" + str(INSTANCE_DIR / "library.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    FINE_PER_DAY = 5
    LOAN_DAYS = 14
