import sys
import os
import configparser
import spotipy
import spotipy.util as util
import signal
import RPi.GPIO as GPIO
import time

# some global stuff.
# initial status
current_state = 'context'
# initial Configuration file
dir = os.path.dirname(__file__)
config_file = os.path.join(dir, '..', 'config', 'eink_options.ini')
# Configuration for the matrix
config = configparser.ConfigParser()
config.read(config_file)
# Gpio pins for each button (from top to bottom)
BUTTONS = [5, 6, 16, 24]
# These correspond to buttons A, B, C and D respectively
LABELS = ['A', 'B', 'C', 'D']

playlists = None
current_playlist_index = 0

def get_state(current_state: str) -> str:
    states = ['track', 'context', 'off']
    index = states.index(current_state)
    if index < (len(states)-1):
        return states[index+1]
    else:
        return states[0]

# "handle_button" will be called every time a button is pressed
# It receives one argument: the associated input pin.
def handle_button(pin):
    global current_state
    global config
    # do this every time to load the latest refresh token from the displayCoverArt.py->getSongInfo.py
    scope = 'user-read-currently-playing,user-modify-playback-state'
    token = util.prompt_for_user_token(
        username=config['DEFAULT']['username'],
        scope=scope, cache_path=config['DEFAULT']['token_file'])
    if not token:
        print(f"Error with token: {config['DEFAULT']['token_file']}")
        return
    sp = spotipy.Spotify(auth=token)
    label = LABELS[BUTTONS.index(pin)]
    if label == 'A':
        sp.next_track()
        return
    if label == 'B':
        sp.previous_track()
        return
    if label == 'C':
        try:
            sp.start_playback()
        except spotipy.exceptions.SpotifyException:
            sp.pause_playback()
        return
    if label == 'D':
        global playlists, current_playlist_index

        if playlists is None:
            # Fetch current user's playlists the first time button is pressed
            playlists = sp.current_user_playlists()
            current_playlist_index = 0  # Start with the first playlist

        if playlists and playlists['items']:
            # Play the current playlist based on the index
            if current_playlist_index < len(playlists['items']):
                playlist = playlists['items'][current_playlist_index]
                print("%4d %s %s" % (current_playlist_index + 1, playlist['uri'], playlist['name']))
                sp.start_playback(context_uri=playlist['uri'])

                # Increment the index for the next button press
                current_playlist_index += 1

                # If the index exceeds the number of playlists, reset it to loop through again
                if current_playlist_index >= len(playlists['items']):
                    current_playlist_index = 0

            # Handle pagination if more playlists are available
            if playlists['next'] and current_playlist_index == 0:
                playlists = sp.next(playlists)

# CTR + C event clean up GPIO setup and exit nicely
def signal_handler(sig, frame):
    GPIO.cleanup()
    sys.exit(0)

def main():
    # Set up RPi.GPIO with the "BCM" numbering scheme
    GPIO.setmode(GPIO.BCM)

    # Buttons connect to ground when pressed, so we should set them up
    # with a "PULL UP", which weakly pulls the input signal to 3.3V.
    GPIO.setup(BUTTONS, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Register the callback for CTRL+C handling
    signal.signal(signal.SIGINT, signal_handler)
    # Register the callback for SIGTERM handling
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while True:
            for pin in BUTTONS:
                if GPIO.input(pin) == GPIO.LOW:  # Button pressed
                    handle_button(pin)
                    time.sleep(0.2)  # Debounce delay
            time.sleep(0.1)  # Polling interval to avoid high CPU usage

    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
