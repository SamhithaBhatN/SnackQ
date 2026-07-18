import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DATABASE = os.path.join(BASE_DIR, "database", "SnackQ.db")

class Config:
    SECRET_KEY = "supersecretkey"

    DATABASE = os.path.join(BASE_DIR, "SnackQ.db")

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")

    ALLOWED_EXTENSIONS = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp"
    }