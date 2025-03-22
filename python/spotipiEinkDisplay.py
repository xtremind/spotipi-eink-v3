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

# Recursion limiter to avoid infinite loops in _get_song_info()
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
        # Handle system signals
        signal.signal(signal.SIGTERM, self._handle_sigterm)

        self.delay = delay
        self.config = configparser.ConfigParser()
        self.config.read(os.path.join(os.path.dirname(__file__), '..', 'config', 'eink_options.ini'))

        # ---------------------------------------------------------------------
        # New "idle" feature settings from the current file
        # ---------------------------------------------------------------------
        self.idle_mode = self.config.get('DEFAULT', 'idle_mode', fallback='cycle')
        self.idle_display_time = self.config.getint('DEFAULT', 'idle_display_time', fallback=300)
        self.idle_shuffle = self.config.getboolean('DEFAULT', 'idle_shuffle', fallback=False)
        self.idle_folder = os.path.join(os.path.dirname(__file__), '..', 'config', 'idle_images')
        self.default_idle_image = self.config.get('DEFAULT', 'no_song_cover')
        # Cache idle images for cycling/shuffle
        self.idle_images = self._load_idle_images()
        self.idle_index = 0

        # ---------------------------------------------------------------------
        # Logging setup (merge of old & new)
        # ---------------------------------------------------------------------
        logging.basicConfig(
            format='%(asctime)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            filename=self.config.get('DEFAULT', 'spotipy_log'),
            level=logging.INFO
        )
        logger = logging.getLogger('spotipy_logger')
        # Use rotating file handler to limit log size
        handler = RotatingFileHandler(
            self.config.get('DEFAULT', 'spotipy_log'),
            maxBytes=2000,
            backupCount=3
        )
        logger.addHandler(handler)
        self.logger = logger
        self.logger.info('Logger test: initialization complete')

        # Create a more verbose console logger
        self.logger = self._init_logger()
        self.logger.info('Service instance created')

        # ---------------------------------------------------------------------
        # Set up display model
        # ---------------------------------------------------------------------
        if self.config.get('DEFAULT', 'model') == 'inky':
            from inky.auto import auto
            from inky.inky_uc8159 import CLEAN
            self.inky_auto = auto
            self.inky_clean = CLEAN
            self.logger.info('Loading Pimoroni Inky library')
        elif self.config.get('DEFAULT', 'model') == 'waveshare4':
            from lib import epd4in01f
            self.wave4 = epd4in01f
            self.logger.info('Loading Waveshare 4" library')

        # Track previous song and how many times we’ve refreshed
        self.song_prev = ''
        self.pic_counter = 0

    def _init_logger(self):
        """
        Creates a console logger at DEBUG level and attaches it to
        the 'spotipy_logger' we set up above.
        """
        logger = logging.getLogger('spotipy_logger')
        logger.setLevel(logging.DEBUG)
        stdout_handler = logging.StreamHandler()
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(logging.Formatter('Spotipi eInk Display - %(message)s'))
        logger.addHandler(stdout_handler)
        return logger

    def _handle_sigterm(self, sig, frame):
        self.logger.warning('SIGTERM received, stopping')
        sys.exit(0)

    def _load_idle_images(self):
        """Load all valid image files from the idle folder for shuffle/cycle."""
        images = []
        try:
            if os.path.isdir(self.idle_folder):
                for f in os.listdir(self.idle_folder):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                        images.append(os.path.join(self.idle_folder, f))
        except Exception as e:
            self.logger.error(f"Failed to load idle images: {e}")
            self.logger.error(traceback.format_exc())
        return images

    def _get_idle_image(self):
        """
        Returns an idle image according to idle_mode and idle_shuffle:
          - If no images are found in the idle folder, returns the default image.
          - If shuffle is True, picks randomly.
          - Otherwise cycles through the list in order.
        """
        if not self.idle_images:
            return Image.open(self.default_idle_image)

        if self.idle_shuffle:
            return Image.open(random.choice(self.idle_images))
        else:
            img_path = self.idle_images[self.idle_index]
            self.idle_index = (self.idle_index + 1) % len(self.idle_images)
            return Image.open(img_path)

    def _break_fix(self, text: str, width: int, font: ImageFont, draw: ImageDraw):
        """
        Breaks a string into lines so that each line does not exceed 'width'.
        """
        if not text:
            return
        if isinstance(text, str):
            text = text.split()  # split into words
        lo = 0
        hi = len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            t = ' '.join(text[:mid])
            w = int(draw.textlength(text=t, font=font))
            if w <= width:
                lo = mid
            else:
                hi = mid - 1
        t = ' '.join(text[:lo])
        w = int(draw.textlength(text=t, font=font))
        yield t, w
        yield from self._break_fix(text[lo:], width, font, draw)

    def _fit_text_top_down(self, img: Image, text: str, text_color: str, shadow_text_color: str,
                           font: ImageFont, y_offset: int, font_size: int,
                           x_start_offset: int = 0, x_end_offset: int = 0,
                           offset_text_px_shadow: int = 0) -> int:
        """
        Draw text from top to bottom, wrapping as needed, and return the height used.
        """
        width = img.width - x_start_offset - x_end_offset - offset_text_px_shadow
        draw = ImageDraw.Draw(img)
        pieces = list(self._break_fix(text, width, font, draw))
        y = y_offset
        h_taken_by_text = 0
        for t, _ in pieces:
            if offset_text_px_shadow > 0:
                draw.text((x_start_offset + offset_text_px_shadow, y + offset_text_px_shadow),
                          t, font=font, fill=shadow_text_color)
            draw.text((x_start_offset, y), t, font=font, fill=text_color)
            y += font_size
            h_taken_by_text += font_size
        return h_taken_by_text

    def _fit_text_bottom_up(self, img: Image, text: str, text_color: str, shadow_text_color: str,
                            font: ImageFont, y_offset: int, font_size: int,
                            x_start_offset: int = 0, x_end_offset: int = 0,
                            offset_text_px_shadow: int = 0) -> int:
        """
        Draw text from bottom upward, wrapping as needed, and return the height used.
        """
        width = img.width - x_start_offset - x_end_offset - offset_text_px_shadow
        draw = ImageDraw.Draw(img)
        pieces = list(self._break_fix(text, width, font, draw))
        # If multiple lines, move upward to accommodate them
        if len(pieces) > 1:
            y_offset -= (len(pieces) - 1) * font_size

        h_taken_by_text = 0
        for t, _ in pieces:
            if offset_text_px_shadow > 0:
                draw.text((x_start_offset + offset_text_px_shadow, y_offset + offset_text_px_shadow),
                          t, font=font, fill=shadow_text_color)
            draw.text((x_start_offset, y_offset), t, font=font, fill=text_color)
            y_offset += font_size
            h_taken_by_text += font_size
        return h_taken_by_text

    def _display_clean(self):
        """
        Clears the display (two passes) for either Inky or Waveshare.
        """
        try:
            if self.config.get('DEFAULT', 'model') == 'inky':
                inky = self.inky_auto()
                for _ in range(2):
                    for y in range(inky.height):
                        for x in range(inky.width):
                            inky.set_pixel(x, y, self.inky_clean)
                    inky.show()
                    time.sleep(1.0)
            elif self.config.get('DEFAULT', 'model') == 'waveshare4':
                epd = self.wave4.EPD()
                epd.init()
                epd.Clear()
        except Exception as e:
            self.logger.error(f'Display clean error: {e}')
            self.logger.error(traceback.format_exc())

    def _convert_image_wave(self, img: Image, saturation: int = 2) -> Image:
        """
        Convert an Image to the 7-color format needed by Waveshare 4".
        """
        # Boost saturation
        converter = ImageEnhance.Color(img)
        img = converter.enhance(saturation)
        # Build a palette for 7 colors
        palette_data = [
            0x00, 0x00, 0x00,   # black
            0xff, 0xff, 0xff,   # white
            0x00, 0xff, 0x00,   # green
            0x00, 0x00, 0xff,   # blue
            0xff, 0x00, 0x00,   # red
            0xff, 0xff, 0x00,   # yellow
            0xff, 0x80, 0x00    # orange
        ]
        # Construct a palette image and apply
        palette_image = Image.new('P', (1, 1))
        palette_image.putpalette(palette_data + [0, 0, 0] * 248)
        img.load()
        palette_image.load()
        im = img.im.convert('P', True, palette_image.im)
        return img._new(im)

    def _display_image(self, image: Image, saturation: float = 0.5):
        """
        Displays the Image either on Inky or Waveshare, handling init calls.
        """
        try:
            if self.config.get('DEFAULT', 'model') == 'inky':
                inky = self.inky_auto()
                inky.set_image(image, saturation=saturation)
                inky.show()
            elif self.config.get('DEFAULT', 'model') == 'waveshare4':
                epd = self.wave4.EPD()
                epd.init()
                epd.display(epd.getbuffer(self._convert_image_wave(image)))
                epd.sleep()
        except Exception as e:
            self.logger.error(f'Display image error: {e}')
            self.logger.error(traceback.format_exc())

    def _gen_pic(self, image: Image, artist: str, title: str) -> Image:
        """
        Generates the final composite image with the album artwork (or idle image),
        background blur (if configured), and the text (title/artist).
        """
        album_cover_small_px = self.config.getint('DEFAULT', 'album_cover_small_px')
        offset_px_left = self.config.getint('DEFAULT', 'offset_px_left')
        offset_px_right = self.config.getint('DEFAULT', 'offset_px_right')
        offset_px_top = self.config.getint('DEFAULT', 'offset_px_top')
        offset_px_bottom = self.config.getint('DEFAULT', 'offset_px_bottom')
        offset_text_px_shadow = self.config.getint('DEFAULT', 'offset_text_px_shadow', fallback=0)
        text_direction = self.config.get('DEFAULT', 'text_direction', fallback='top-down')
        background_blur = self.config.getint('DEFAULT', 'background_blur', fallback=0)

        # Dimensions of source image
        bg_w, bg_h = image.size

        # Fit or repeat background
        if self.config.get('DEFAULT', 'background_mode') == 'fit':
            # Resize or crop to the device's final width/height
            target_size = (self.config.getint('DEFAULT', 'width'), self.config.getint('DEFAULT', 'height'))
            if bg_w != target_size[0] or bg_h != target_size[1]:
                image_new = ImageOps.fit(image, target_size, centering=(0.5, 0.5))
            else:
                image_new = image.crop((0, 0, target_size[0], target_size[1]))
        elif self.config.get('DEFAULT', 'background_mode') == 'repeat':
            target_w = self.config.getint('DEFAULT', 'width')
            target_h = self.config.getint('DEFAULT', 'height')
            image_new = Image.new('RGB', (target_w, target_h))
            for x in range(0, target_w, bg_w):
                for y in range(0, target_h, bg_h):
                    image_new.paste(image, (x, y))
        else:
            # Fallback: just crop or do nothing
            target_size = (self.config.getint('DEFAULT', 'width'), self.config.getint('DEFAULT', 'height'))
            image_new = image.crop((0, 0, target_size[0], target_size[1]))

        # If we want a blurred background, do it now (before we paste the small cover)
        if background_blur > 0:
            image_new = image_new.filter(ImageFilter.GaussianBlur(background_blur))

        # If the config says "album_cover_small = True", we paste a smaller version of the image
        if self.config.getboolean('DEFAULT', 'album_cover_small'):
            cover_smaller = image.resize((album_cover_small_px, album_cover_small_px), Image.LANCZOS)
            album_pos_x = (image_new.width - album_cover_small_px) // 2
            image_new.paste(cover_smaller, (album_pos_x, offset_px_top))

        # Prepare fonts
        font_title = ImageFont.truetype(self.config.get('DEFAULT', 'font_path'),
                                        self.config.getint('DEFAULT', 'font_size_title'))
        font_artist = ImageFont.truetype(self.config.get('DEFAULT', 'font_path'),
                                         self.config.getint('DEFAULT', 'font_size_artist'))

        draw = ImageDraw.Draw(image_new)

        # Render text depending on top-down or bottom-up
        if text_direction == 'top-down':
            # Place the song title first
            title_position_y = offset_px_top + album_cover_small_px + 10
            title_height = self._fit_text_top_down(
                img=image_new,
                text=title,
                text_color='white',
                shadow_text_color='black',
                font=font_title,
                font_size=self.config.getint('DEFAULT', 'font_size_title'),
                y_offset=title_position_y,
                x_start_offset=offset_px_left,
                x_end_offset=offset_px_right,
                offset_text_px_shadow=offset_text_px_shadow
            )
            # Then place the artist text just below title
            artist_position_y = title_position_y + title_height
            self._fit_text_top_down(
                img=image_new,
                text=artist,
                text_color='white',
                shadow_text_color='black',
                font=font_artist,
                font_size=self.config.getint('DEFAULT', 'font_size_artist'),
                y_offset=artist_position_y,
                x_start_offset=offset_px_left,
                x_end_offset=offset_px_right,
                offset_text_px_shadow=offset_text_px_shadow
            )

        elif text_direction == 'bottom-up':
            # Place the artist first, hugging bottom
            artist_position_y = image_new.height - (offset_px_bottom + self.config.getint('DEFAULT', 'font_size_artist'))
            artist_height = self._fit_text_bottom_up(
                img=image_new,
                text=artist,
                text_color='white',
                shadow_text_color='black',
                font=font_artist,
                font_size=self.config.getint('DEFAULT', 'font_size_artist'),
                y_offset=artist_position_y,
                x_start_offset=offset_px_left,
                x_end_offset=offset_px_right,
                offset_text_px_shadow=offset_text_px_shadow
            )
            # Then title above that
            title_position_y = artist_position_y - self.config.getint('DEFAULT', 'font_size_title') - artist_height
            self._fit_text_bottom_up(
                img=image_new,
                text=title,
                text_color='white',
                shadow_text_color='black',
                font=font_title,
                font_size=self.config.getint('DEFAULT', 'font_size_title'),
                y_offset=title_position_y,
                x_start_offset=offset_px_left,
                x_end_offset=offset_px_right,
                offset_text_px_shadow=offset_text_px_shadow
            )
        return image_new  # end of _gen_pic

    def _display_update_process(self, song_request: list):
        """
        Decides how to generate and display the final image based on
        whether a song is playing or not. Cleans the display after
        'display_refresh_counter' cycles to reduce e-paper ghosting.
        """
        if song_request:
            # song_request is [song_title, album_url, artist]
            try:
                cover_response = requests.get(song_request[1], stream=True)
                cover_response.raise_for_status()
                cover = Image.open(cover_response.raw)
                image = self._gen_pic(cover, song_request[2], song_request[0])
            except Exception as e:
                self.logger.error(f"Failed to fetch/open album cover: {e}")
                self.logger.error(traceback.format_exc())
                # fallback to default idle/no-song image if there's a problem
                fallback_cover = Image.open(self.default_idle_image)
                image = self._gen_pic(fallback_cover, song_request[2], song_request[0])
        else:
            # No song is playing -> use the idle logic
            idle_img = self._get_idle_image()
            image = self._gen_pic(idle_img, "spotipi-eink", "No song playing")

        # Clean the screen after N refreshes
        refresh_limit = self.config.getint('DEFAULT', 'display_refresh_counter', fallback=20)
        if self.pic_counter > refresh_limit:
            self._display_clean()
            self.pic_counter = 0

        # Display the final composed image
        self._display_image(image)
        self.pic_counter += 1

    @limit_recursion(limit=10)
    def _get_song_info(self) -> list:
        """
        Retrieves the currently playing track (or episode) from Spotify.
        Returns [song_title, album_cover_url, artist_name] or [] if none/ad.
        """
        scope = 'user-read-currently-playing,user-modify-playback-state'
        username = self.config.get('DEFAULT', 'username')
        token_file = self.config.get('DEFAULT', 'token_file')
        token = util.prompt_for_user_token(username=username, scope=scope, cache_path=token_file)

        if token:
            sp = spotipy.Spotify(auth=token)
            result = sp.currently_playing(additional_types='episode')
            if result:
                try:
                    ctype = result.get('currently_playing_type', 'unknown')
                    if ctype == 'episode':
                        song = result["item"]["name"]
                        artist = result["item"]["show"]["name"]
                        cover_url = result["item"]["images"][0]["url"]
                        return [song, cover_url, artist]
                    elif ctype == 'track':
                        song = result["item"]["name"]
                        # Join all artists with comma
                        artist = ', '.join(a["name"] for a in result["item"]["artists"])
                        cover_url = result["item"]["album"]["images"][0]["url"]
                        return [song, cover_url, artist]
                    elif ctype == 'ad':
                        # Advertisement playing => treat as no song
                        return []
                    elif ctype == 'unknown':
                        # The API might return unknown temporarily
                        time.sleep(0.01)
                        return self._get_song_info()
                    self.logger.error(f"Unsupported currently_playing_type: {ctype}")
                    return []
                except TypeError:
                    # Spotipy occasionally returns None or partial data
                    self.logger.error("TypeError from Spotipy, retrying...")
                    time.sleep(0.01)
                    return self._get_song_info()
            else:
                # result was None -> no track currently playing
                return []
        else:
            self.logger.error(f"Error: Can't get token for {username}")
            return []

    def start(self):
        """
        Main loop: polls Spotify for current track,
        updates e-ink display or idle image as needed.
        """
        self.logger.info('Service started')
        # Clean screen initially
        self._display_clean()

        try:
            while True:
                try:
                    # Check Spotify for what's playing
                    song_request = self._get_song_info()

                    if song_request:
                        # Compare new track ID to old
                        new_song_key = song_request[0] + song_request[1]
                        if self.song_prev != new_song_key:
                            self.song_prev = new_song_key
                            self._display_update_process(song_request)
                    else:
                        # No song playing scenario
                        if self.song_prev != 'NO_SONG':
                            self.song_prev = 'NO_SONG'
                            self._display_update_process([])
                except Exception as e:
                    self.logger.error(f"Error in main loop: {e}")
                    self.logger.error(traceback.format_exc())

                time.sleep(self.delay)

        except KeyboardInterrupt:
            self.logger.info("Service stopping via KeyboardInterrupt")
            sys.exit(0)
