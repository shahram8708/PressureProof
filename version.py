from datetime import datetime
import hashlib

APP_VERSION = "1.0.0"
BUILD_TIME = datetime.utcnow().isoformat()


def get_cache_version():
    digest = hashlib.md5(BUILD_TIME.encode("utf-8")).hexdigest()
    return f"{APP_VERSION}-{digest[:8]}"
