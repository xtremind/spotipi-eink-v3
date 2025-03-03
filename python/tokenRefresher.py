import os
import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
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
    logger.error("Missing Spotify API environment variables! Check your systemd-env-file.")
    exit(1)

sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope="user-read-currently-playing user-modify-playback-state user-read-playback-state",
    cache_path=CACHE_PATH
)

sp = None

def refresh_token_if_needed():
    """Checks if the access token is about to expire and refreshes it if necessary."""
    global sp
    token_info = sp_oauth.get_cached_token()

    if not token_info:
        logger.error("No saved token found! Please authenticate manually once.")
        return

    expires_at = token_info["expires_at"]
    current_time = int(time.time())

    if expires_at - current_time < 300:
        logger.info("Token is about to expire. Refreshing...")
        try:
            new_token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            if new_token_info:
                logger.info("Access token successfully refreshed!")
                sp = spotipy.Spotify(auth=new_token_info["access_token"])
            else:
                logger.error("Error while refreshing access token!")
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")

def keep_spotify_alive():
    """Send a harmless API request to keep the Spotify session alive."""
    global sp
    if not sp:
        token_info = sp_oauth.get_cached_token()
        if token_info:
            sp = spotipy.Spotify(auth=token_info["access_token"])
        else:
            logger.error("No valid token found for Keep-Alive.")
            return

    try:
        logger.info("Sending Keep-Alive request to Spotify API...")
        current_playback = sp.current_playback()
        if current_playback:
            logger.info("Spotify session is active.")
        else:
            logger.info("No active playback, but connection maintained.")
    except spotipy.exceptions.SpotifyException as e:
        logger.warning(f"Spotify API request failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during Keep-Alive request: {e}")

if __name__ == "__main__":
    logger.info("Spotify Token Refresh & Keep-Alive Service started...")

    while True:
        start_time = time.time()
        refresh_token_if_needed()
        keep_spotify_alive()
        elapsed_time = time.time() - start_time
        sleep_time = max(300 - elapsed_time, 0)
        time.sleep(sleep_time)
