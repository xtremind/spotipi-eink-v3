import sys
from spotipy.oauth2 import SpotifyOAuth

def main():
    if len(sys.argv) > 1:
        username = sys.argv[1]
        
        # Expanded scope to include playlist-related permissions
        scope = (
            'user-read-currently-playing,user-modify-playback-state,'
            'playlist-read-private,playlist-read-collaborative,'
            'playlist-modify-public,playlist-modify-private'
        )

        # This way removes the need for a browser, it will instead give the URL to visit in the terminal
        auth = SpotifyOAuth(scope=scope, open_browser=False)
        token = auth.get_access_token(as_dict=False)
        
        if not token:
            print('Error unable to get token', file=sys.stderr)
            sys.exit(-1)
    else:
        print(f"Usage: {sys.argv[0]} username")
        sys.exit()

if __name__ == "__main__":
    main()
