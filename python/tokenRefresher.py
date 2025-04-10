import os
import time
import threading
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging

# Basic logging configuration
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("SpotifyTokenRefresher")

# Load environment variables from the systemd drop-in file
ENV_FILE = "/etc/systemd/system/spotipi-eink-display.service.d/spotipi-eink-display_env.conf"
if os.path.exists(ENV_FILE):
    with open(ENV_FILE, "r") as f:
        for line in f:
            if line.startswith("Environment="):
                try:
                    # Example line: Environment="SPOTIPY_CLIENT_ID=abc123"
                    env_entry = line.strip().split("=", 1)[1]
                    key, value = env_entry.split("=", 1)
                    key = key.strip().strip('"')
                    value = value.strip().strip('"')
                    os.environ[key] = value
                except ValueError as e:
                    logger.error(f"Error while loading ENV File: {line} - {e}")

# Set up token cache path relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(SCRIPT_DIR, "../config/.cache")

# Get required Spotify credentials from environment
CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI")

if not all([CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
    logger.error("Missing Spotify API environment variables! Check your systemd-env-file.")
    exit(1)

# Set up Spotify OAuth
sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope="user-read-currently-playing user-modify-playback-state user-read-playback-state",
    cache_path=CACHE_PATH
)

# Global Spotify instance
sp = None

def refresh_and_keepalive():
    """Background function to refresh the token and send keep-alive pings."""
    global sp
    check_interval = 60  # seconds between checks
    backoff = 1          # initial backoff in seconds
    max_backoff = 60     # maximum backoff

    while True:
        start_time = time.time()
        try:
            token_info = sp_oauth.get_cached_token()
            if not token_info:
                logger.error("No cached token found! Please authenticate manually once.")
            else:
                expires_at = token_info.get("expires_at")
                current_time = int(time.time())
                remaining = expires_at - current_time if expires_at else None
                logger.info(f"Token expires in {remaining} seconds (expires_at: {expires_at}, current_time: {current_time}).")
                
                # Refresh token if it's about to expire in less than 60 seconds
                if remaining is not None and remaining < 60:
                    logger.info("Token is about to expire. Refreshing token...")
                    new_token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
                    if new_token_info and "access_token" in new_token_info:
                        logger.info("Token refreshed successfully.")
                        sp = spotipy.Spotify(auth=new_token_info["access_token"])
                        backoff = 1  # reset backoff after successful refresh
                    else:
                        logger.error("Failed to refresh token!")
                        raise Exception("Token refresh failed.")
                else:
                    # If we don't have an instance yet, initialize it.
                    if sp is None:
                        sp = spotipy.Spotify(auth=token_info["access_token"])

                    # Keep-alive: Send a simple API request
                    logger.info("Sending keep-alive request to Spotify API...")
                    current_playback = sp.current_playback()
                    if current_playback:
                        logger.info("Spotify playback detected.")
                    else:
                        logger.info("No active playback (keep-alive still successful).")
            # Reset backoff on successful run
            backoff = 1
        except Exception as e:
            logger.error(f"Error during token refresh/keep-alive: {e}")
            logger.info(f"Backing off for {backoff} seconds...")
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
            continue  # Skip normal sleep, retry after backoff

        elapsed = time.time() - start_time
        sleep_time = max(check_interval - elapsed, 0)
        time.sleep(sleep_time)

def start_background_thread():
    """Starts the refresh & keep-alive process in a dedicated background thread."""
    thread = threading.Thread(target=refresh_and_keepalive, daemon=True)
    thread.start()
    logger.info("Spotify Token Refresh & Keep-Alive background thread started.")
    return thread

if __name__ == "__main__":
    logger.info("Starting Spotify Token Refresh & Keep-Alive Service...")
    start_background_thread()

    # Keep the main thread alive indefinitely.
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Spotify Token Refresh & Keep-Alive Service stopping due to KeyboardInterrupt.")
