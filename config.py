from pathlib import Path

APP_NAME = "ALBA v2 | Plataforma de Selección"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "alba_v2.db"

DATA_DIR.mkdir(exist_ok=True)
