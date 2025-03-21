import time
import sys
import logging
from logging.handlers import RotatingFileHandler
import spotipy
import spotipy.util as util
import os
import traceback
import configparser
import requests
import signal
import random
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter

# Recursion limiter for get song info to avoid infinite loops
def limit_recursion(limit):
    def inner(func):
        func.count = 0

        def wrapper(*args, **kwargs):
            func.count += 1
            if func.count < limit:
                result = func(*args, **kwargs)
            else:
                result = None
            func.count -= 1
            return result
        return wrapper
    return inner

class SpotipiEinkDisplay:
    def __init__(self, delay=1):
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        self.delay = delay
        
        # Configuration for the display
        self.config = configparser.ConfigParser()
        self.config.read(os.path.join(os.path.dirname(__file__), '..', 'config', 'eink_options.ini'))

        # Load idle mode settings
        self.idle_mode = self.config.get('DEFAULT', 'idle_mode', fallback='cycle')
        self.idle_display_time = self.config.getint('DEFAULT', 'idle_display_time', fallback=300)
        self.idle_shuffle = self.config.getboolean('DEFAULT', 'idle_shuffle', fallback=False)
        self.idle_folder = os.path.join(os.path.dirname(__file__), '..', 'config', 'idle_images')
        self.default_idle_image = self.config.get('DEFAULT', 'no_song_cover')

        # Set up logging
        logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S', 
                            filename=self.config.get('DEFAULT', 'spotipy_log'), level=logging.INFO)
        self.logger = logging.getLogger('spotipy_logger')
        handler = RotatingFileHandler(self.config.get('DEFAULT', 'spotipy_log'), maxBytes=2000, backupCount=3)
        self.logger.addHandler(handler)
        
        self.song_prev = ''
        self.pic_counter = 0
        
        if self.config.get('DEFAULT', 'model') == 'inky':
            from inky.auto import auto
            from inky.inky_uc8159 import CLEAN
            self.inky_auto = auto
            self.inky_clean = CLEAN
            self.logger.info('Loading Pimoroni Inky lib')
        elif self.config.get('DEFAULT', 'model') == 'waveshare4':
            from lib import epd4in01f
            self.wave4 = epd4in01f
            self.logger.info('Loading Waveshare 4" lib')

    def _handle_sigterm(self, sig, frame):
        self.logger.warning('SIGTERM received, stopping')
        sys.exit(0)

    def _cycle_idle_images(self):
        """Cycles through images in the idle folder while idle."""
        images = [os.path.join(self.idle_folder, img) for img in os.listdir(self.idle_folder) if img.endswith(('.png', '.jpg', '.jpeg'))]

        if not images:
            images.append(self.default_idle_image)  # Fallback to default

        if self.idle_shuffle:
            random.shuffle(images)

        for image_path in images:
            if self._get_song_info():
                return  # Exit idle mode if music starts

            self.logger.info(f"Displaying idle image: {image_path}")
            self._display_update_process([None, image_path, ""])
            time.sleep(self.idle_display_time)

    def _display_update_process(self, song_request: list):
        """Handles updating the display with either album art or idle images."""
        if song_request:
            image = self._gen_pic(Image.open(requests.get(song_request[1], stream=True).raw), song_request[2], song_request[0])
        else:
            if self.idle_mode == "cycle":
                self.logger.info("Entering idle image cycling mode.")
                self._cycle_idle_images()
                return  
            else:
                image = self._gen_pic(Image.open(self.default_idle_image), 'spotipi-eink', 'No song playing')

        if self.pic_counter > self.config.getint('DEFAULT', 'display_refresh_counter'):
            self._display_clean()
            self.pic_counter = 0

        self._display_image(image)
        self.pic_counter += 1

    @limit_recursion(limit=10)
    def _get_song_info(self) -> list:
        """Gets the currently playing song from Spotify API."""
        scope = 'user-read-currently-playing,user-modify-playback-state'
        token = util.prompt_for_user_token(username=self.config.get('DEFAULT', 'username'), scope=scope, cache_path=self.config.get('DEFAULT', 'token_file'))
        if token:
            sp = spotipy.Spotify(auth=token)
            result = sp.currently_playing(additional_types='episode')
            if result:
                try:
                    if result['currently_playing_type'] == 'episode':
                        return [result["item"]["name"], result["item"]["images"][0]["url"], result["item"]["show"]["name"]]
                    if result['currently_playing_type'] == 'track':
                        artist_names = ', '.join([artist["name"] for artist in result["item"]["artists"]])
                        return [result["item"]["name"], result["item"]["album"]["images"][0]["url"], artist_names]
                    if result['currently_playing_type'] in ['unknown', 'ad']:
                        return []
                except TypeError:
                    self.logger.error('Error: TypeError')
                    time.sleep(0.01)
                    return self._get_song_info()
            return []
        else:
            self.logger.error(f"Error: Can't get token for {self.config.get('DEFAULT', 'username')}")
            return []

    def start(self):
    """Main service loop that continuously checks for new songs and updates display accordingly."""
    self.logger.info('Service started')
    self._display_clean()

    try:
        while True:
            try:
                song_request = self._get_song_info()

                if song_request:
                    song_key = song_request[0] + song_request[1]
                    if self.song_prev != song_key:
                        self.song_prev = song_key
                        self._display_update_process(song_request=song_request)

                else:
                    if self.song_prev != 'NO_SONG':
                        self.song_prev = 'NO_SONG'
                        self.logger.info("Entering idle mode (no song playing or API returned nothing)")
                    self._cycle_idle_images()  # Will loop inside until music starts again

            except Exception as e:
                self.logger.error(f'Error during update loop: {e}')
                self.logger.error(traceback.format_exc())
                if self.song_prev != 'NO_SONG':
                    self.song_prev = 'NO_SONG'
                    self.logger.info("Entering idle mode due to exception")
                self._cycle_idle_images()  # Same fallback behavior

            time.sleep(self.delay)
    except KeyboardInterrupt:
        self.logger.info('Service stopping')
        sys.exit(0)
