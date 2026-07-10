from pathlib import Path

APP_NAME = "Alba | Plataforma de Selección"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "database"
EXPORT_DIR = BASE_DIR / "exports"
DB_PATH = DATA_DIR / "alba.db"

DATA_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

DECISIONS = ["PENDIENTE", "AVANZAR", "REVISIÓN HUMANA", "NO AVANZAR"]
APPLICATION_STAGES = [
    "CV RECIBIDO",
    "PRESELECCIÓN CV",
    "ENTREVISTA ALBA",
    "REVISIÓN HUMANA",
    "FINALIZADO",
]
