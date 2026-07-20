import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Config:
    SECRET_KEY = "supersecretkey"

    DATABASE = os.path.join(BASE_DIR, "SnackQ.db")

    ADMIN_PASSWORD = "Admin@2026"

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")

    ALLOWED_EXTENSIONS = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp"
    }