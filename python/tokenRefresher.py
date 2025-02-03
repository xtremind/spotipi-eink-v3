import os
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("SpotifyTokenRefresher")

ENV_FILE = "/etc/systemd/system/spotipi-eink-display.service.d/spotipi-eink-display_env.conf"

if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r") as f:
        for line in f:
            if line.startswith("Environment="):
                try:
                    env_entry = line.strip().split("=", 1)[1]
                    key, value = env_entry.split("=", 1)
                    key = key.strip().strip('"')
                    value = value.strip().strip('"')
                    os.environ[key] = value
                except ValueError as e:
                    logger.error(f"Error while loading ENV File: {line} - {e}")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(SCRIPT_DIR, "../config/.cache")

CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI")

if not all([CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
    logger.error("Missing Spotify API envoirenment variables! Check your systemd-env-file.")
    exit(1)

sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope="user-read-currently-playing,user-modify-playback-state",
    cache_path=CACHE_PATH
)


def refresh_token_if_needed():
    """chekcs whether the access token is about to expire and renews it if necessary"""
    token_info = sp_oauth.get_cached_token()

    if not token_info:
        logger.error("No saved token found! Please authenticate manually once.")
        return

    expires_at = token_info["expires_at"]
    current_time = int(time.time())

    if expires_at - current_time < 300:
        logger.info("Token is about to expire. Refreshing...")
        new_token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])

        if new_token_info:
            logger.info("Access token successfully refreshed!")
        else:
            logger.error("Error while refreshing access token!")


if __name__ == "__main__":
    logger.info("Spotify Token Refresh Service started...")
    while True:
        refresh_token_if_needed()
        time.sleep(60)
