#!/bin/bash
#
# Merged setup script: oldsetup.sh + currentsetup.sh
# --------------------------------------------------
# This script installs system packages, creates a Python venv, configures
# the "spotipi-eink" repository, prompts for Spotify credentials, and
# ensures idle-images config lines are present. It also sets up systemd
# services for the display, token refresher, and optional button service.
#
# NOTE: Run as a normal user (not root). The script calls `sudo` for steps
# that require elevated privileges.


### 0) Don’t run as root
if [[ $EUID -eq 0 ]]; then
  echo "This script must NOT be run as root" 1>&2
  exit 1
fi

### 1) Update system packages
echo "###### Update Packages list"
sudo apt update
echo
echo "###### Update to the latest"
sudo apt upgrade -y

### 2) Install system packages
echo
echo "###### Ensure system packages are installed:"
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-numpy \
    git \
    libopenjp2-7 \
    libjpeg-dev

### 3) Enable SPI & I2C
echo
echo "###### Enabling SPI"
sudo raspi-config nonint do_spi 0
echo "...done"
echo

echo "###### Enabling I2C"
sudo raspi-config nonint do_i2c 0
echo "...done"
echo

### 4) Remove old spotipi-eink if found
if [ -d "spotipi-eink" ]; then
    echo "Old installation found deleting it"
    sudo rm -rf spotipi-eink
fi
if [ -d "spotipi-eink" ]; then
    echo "Old installation found deleting it"
    sudo rm -rf spotipi-eink
fi

### 5) Clone repo
echo
echo "###### Clone spotipy-eink git"
git clone https://github.com/Canterrain/spotipi-eink
echo "Switching into instalation directory"
cd spotipi-eink
install_path=$(pwd)
echo

### 6) Create python virtual environment & install dependencies
echo "##### Creating Spotipi Python environment"
python3 -m venv --system-site-packages spotipienv
echo "Activating Spotipi Python environment"
source "${install_path}/spotipienv/bin/activate"

echo "Installing Python packages from requirements.txt"
pip3 install --upgrade -r requirements.txt
echo "##### Spotipi Python environment created" 
echo

### 7) Create config folder and idle_images subfolder
if ! [ -d "${install_path}/config" ]; then
    echo "Creating ${install_path}/config path"
    mkdir -p "${install_path}/config"
fi
# Ensure idle_images directory exists
mkdir -p "${install_path}/config/idle_images"

### 8) Prepare eink_options.ini
EINK_CONFIG_FILE="${install_path}/config/eink_options.ini"
if [ -f "$EINK_CONFIG_FILE" ]; then
    echo "Existing config file found at $EINK_CONFIG_FILE"
else
    echo "No eink_options.ini found; creating a minimal default."
    cat <<EOF > "$EINK_CONFIG_FILE"
[DEFAULT]
# Idle mode configuration
idle_mode = cycle
idle_display_time = 300
idle_shuffle = false

# Basic placeholders (will be overwritten below)
no_song_cover = ${install_path}/resources/default.jpg
spotipy_log = ${install_path}/log/spotipy.log
EOF
fi

# Function to ensure a config option is present
ensure_config_option() {
    local key="$1"
    local value="$2"
    if ! grep -q "^$key\s*=" "$EINK_CONFIG_FILE"; then
        echo "$key = $value" >> "$EINK_CONFIG_FILE"
    fi
}

# Make sure essential lines are present
ensure_config_option "no_song_cover" "${install_path}/resources/default.jpg"
ensure_config_option "spotipy_log"   "${install_path}/log/spotipy.log"

# We’ll fill in more config entries after the user chooses the display.

### 9) Generate Spotify token (prompt user for ID, secret, redirect, username)
echo
echo "###### Generate Spotify Token"
cd "${install_path}/config"

# REMOVE OLD TOKEN to force re-authentication
echo "Removing old Spotify token to apply new permissions..."
rm -f "${install_path}/config/.cache"

echo "Enter your Spotify Client ID:"
read spotify_client_id
export SPOTIPY_CLIENT_ID="$spotify_client_id"

echo "Enter your Spotify Client Secret:"
read spotify_client_secret
export SPOTIPY_CLIENT_SECRET="$spotify_client_secret"

echo "Enter your Spotify Redirect URI:"
read spotify_redirect_uri
export SPOTIPY_REDIRECT_URI="$spotify_redirect_uri"

echo "Enter your Spotify username:"
read spotify_username

# Attempt to generate the token
python3 "${install_path}/python/generateToken.py" "$spotify_username"

# Check if token was created
if [ -f "${install_path}/config/.cache" ]; then
    spotify_token_path="${install_path}/config/.cache"
    echo "Spotify token located at $spotify_token_path"
else
    echo "Unable to find ${install_path}/config/.cache"
    echo "Please enter the full path to your spotify token file (including .cache):"
    read spotify_token_path
fi

echo "###### Spotify Token Created"
cd "${install_path}"
echo

### 10) Ask which display model the user wants
update_config_txt() {
    echo
    echo "###### Updating /boot/firmware/config.txt to add SPI overlay"
    config_file="/boot/firmware/config.txt"
    if [ ! -f "$config_file" ]; then
        echo "File $config_file does not exist, skipping overlay injection..."
        return
    fi

    if ! grep -q "dtoverlay=spi0-0cs" "$config_file"; then
        echo "Adding configuration to ${config_file}"
        sudo tee -a "$config_file" > /dev/null <<EOL

# Additional config from spotipi-eink setup
dtoverlay=spi0-0cs
EOL
        echo "Configuration added to ${config_file}"
    else
        echo "Configuration already exists in ${config_file}"
    fi
}

echo
echo "###### Display setup"
PS3="Please select your Display Model: "
options=(
    "Pimoroni Inky Impression 4 (640x400)"
    "Waveshare 4.01inch ACeP 4 (640x400)"
    "Pimoroni Inky Impression 5.7 (600x448)"
    "Pimoroni Inky Impression 7.3 (800x480)"
)
select opt in "${options[@]}"
do
    case $opt in
        "Pimoroni Inky Impression 4 (640x400)")
            echo "[DEFAULT]" >> "$EINK_CONFIG_FILE"
            echo "width = 640" >> "$EINK_CONFIG_FILE"
            echo "height = 400" >> "$EINK_CONFIG_FILE"
            echo "album_cover_small_px = 200" >> "$EINK_CONFIG_FILE"
            echo "model = inky" >> "$EINK_CONFIG_FILE"
            BUTTONS=1
            update_config_txt
            break
            ;;
        "Waveshare 4.01inch ACeP 4 (640x400)")
            echo "[DEFAULT]" >> "$EINK_CONFIG_FILE"
            echo "width = 640" >> "$EINK_CONFIG_FILE"
            echo "height = 400" >> "$EINK_CONFIG_FILE"
            echo "album_cover_small_px = 200" >> "$EINK_CONFIG_FILE"
            echo "model = waveshare4" >> "$EINK_CONFIG_FILE"
            BUTTONS=0
            break
            ;;
        "Pimoroni Inky Impression 5.7 (600x448)")
            echo "[DEFAULT]" >> "$EINK_CONFIG_FILE"
            echo "width = 600" >> "$EINK_CONFIG_FILE"
            echo "height = 448" >> "$EINK_CONFIG_FILE"
            echo "album_cover_small_px = 250" >> "$EINK_CONFIG_FILE"
            echo "model = inky" >> "$EINK_CONFIG_FILE"
            BUTTONS=1
            update_config_txt
            break
            ;;
        "Pimoroni Inky Impression 7.3 (800x480)")
            echo "[DEFAULT]" >> "$EINK_CONFIG_FILE"
            echo "width = 800" >> "$EINK_CONFIG_FILE"
            echo "height = 480" >> "$EINK_CONFIG_FILE"
            echo "album_cover_small_px = 300" >> "$EINK_CONFIG_FILE"
            echo "model = inky" >> "$EINK_CONFIG_FILE"
            BUTTONS=1
            update_config_txt
            break
            ;;
        *)
            echo "invalid option $REPLY"
            ;;
    esac
done

### 11) Add more default config lines for text direction, offsets, etc.
echo
echo "###### Creating default config entries and files"
{
  echo "; disable smaller album cover set to False"
  echo "; if disabled top offset is still calculated as offset_px_top + album_cover_small_px"
  echo "album_cover_small = False"
  echo "; Blur intensity for the background image if album_cover_small = True"
  echo "; 0 = no blur, higher values = more blur"
  echo "background_blur = 5"
  echo "; cleans the display every 20 pictures (roughly). This can take ~60 seconds for a full clean."
  echo "display_refresh_counter = 20"
  echo "username = ${spotify_username}"
  echo "token_file = ${spotify_token_path}"
  echo "no_song_cover = ${install_path}/resources/default.jpg"
  echo "spotipy_log = ${install_path}/log/spotipy.log"
  echo "font_path = ${install_path}/resources/CircularStd-Bold.otf"
  echo "font_size_title = 45"
  echo "font_size_artist = 35"
  echo "offset_px_left = 20"
  echo "offset_px_right = 20"
  echo "offset_px_top = 0"
  echo "offset_px_bottom = 20"
  echo "offset_text_px_shadow = 4"
  echo "; text_direction possible values: top-down or bottom-up"
  echo "text_direction = bottom-up"
  echo "; possible modes are fit or repeat"
  echo "background_mode = fit"
} >> "$EINK_CONFIG_FILE"

echo "done updating default config: $EINK_CONFIG_FILE"

### 12) Make sure log directory exists
if ! [ -d "${install_path}/log" ]; then
    echo "creating ${install_path}/log"
    mkdir "${install_path}/log"
fi
echo

### 13) spotipi-eink-display service installation
echo "###### Spotipi-eink-display systemd service"
if [ -f "/etc/systemd/system/spotipi-eink-display.service" ]; then
    echo
    echo "Removing old spotipi-eink-display service:"
    sudo systemctl stop spotipi-eink-display
    sudo systemctl disable spotipi-eink-display
    sudo rm -rf /etc/systemd/system/spotipi-eink-display.*
    sudo systemctl daemon-reload
    echo "...done"
fi

UID_TO_USE=$(id -u)
GID_TO_USE=$(id -g)

echo
echo "Creating spotipi-eink-display service:"
sudo cp "${install_path}/setup/service_template/spotipi-eink-display.service" /etc/systemd/system/
sudo sed -i -e "/\[Service\]/a ExecStart=${install_path}/spotipienv/bin/python3 ${install_path}/python/spotipiEinkDisplay.py" /etc/systemd/system/spotipi-eink-display.service
sudo sed -i -e "/ExecStart/a WorkingDirectory=${install_path}" /etc/systemd/system/spotipi-eink-display.service
sudo sed -i -e "/EnvironmentFile/a User=${UID_TO_USE}" /etc/systemd/system/spotipi-eink-display.service
sudo sed -i -e "/User/a Group=${GID_TO_USE}" /etc/systemd/system/spotipi-eink-display.service
sudo mkdir /etc/systemd/system/spotipi-eink-display.service.d
spotipi_env_path=/etc/systemd/system/spotipi-eink-display.service.d/spotipi-eink-display_env.conf
sudo touch "$spotipi_env_path"
echo "[Service]"           | sudo tee -a "$spotipi_env_path" >/dev/null
echo "Environment=\"SPOTIPY_CLIENT_ID=${spotify_client_id}\""     | sudo tee -a "$spotipi_env_path" >/dev/null
echo "Environment=\"SPOTIPY_CLIENT_SECRET=${spotify_client_secret}\"" | sudo tee -a "$spotipi_env_path" >/dev/null
echo "Environment=\"SPOTIPY_REDIRECT_URI=${spotify_redirect_uri}\""   | sudo tee -a "$spotipi_env_path" >/dev/null

sudo systemctl daemon-reload
sudo systemctl start spotipi-eink-display
sudo systemctl enable spotipi-eink-display
echo "...done"
echo

### 14) spotipi-eink-token-refresher service
echo "Creating spotipi-eink-token-refresher service:"
if [ -f "/etc/systemd/system/spotipi-eink-token-refresher.service" ]; then
    sudo systemctl stop spotipi-eink-token-refresher
    sudo systemctl disable spotipi-eink-token-refresher
    sudo rm -f /etc/systemd/system/spotipi-eink-token-refresher.*
fi

sed "s|{{ INSTALL_PATH }}|${install_path}|g; \
     s|{{ USER_ID }}|${UID_TO_USE}|g; \
     s|{{ GROUP_ID }}|${GID_TO_USE}|g" \
    "${install_path}/setup/service_template/spotipi-eink-token-refresher.service" \
    | sudo tee /etc/systemd/system/spotipi-eink-token-refresher.service > /dev/null

sudo chmod 644 /etc/systemd/system/spotipi-eink-token-refresher.service
sudo mkdir -p /etc/systemd/system/spotipi-eink-token-refresher.service.d

# Reuse the environment file from display service or create new
sudo mkdir -p /etc/systemd/system/spotipi-eink-display.service.d
spotipi_env_path=/etc/systemd/system/spotipi-eink-display.service.d/spotipi-eink-display_env.conf
if [ ! -f "$spotipi_env_path" ]; then
    sudo touch "$spotipi_env_path"
    echo "[Service]"           | sudo tee -a "$spotipi_env_path" > /dev/null
    echo "Environment=\"SPOTIPY_CLIENT_ID=${spotify_client_id}\""     | sudo tee -a "$spotipi_env_path" > /dev/null
    echo "Environment=\"SPOTIPY_CLIENT_SECRET=${spotify_client_secret}\"" | sudo tee -a "$spotipi_env_path" > /dev/null
    echo "Environment=\"SPOTIPY_REDIRECT_URI=${spotify_redirect_uri}\""   | sudo tee -a "$spotipi_env_path" > /dev/null
fi

sudo systemctl daemon-reload
sudo systemctl enable --now spotipi-eink-token-refresher.service
echo "...done"
echo

### 15) Buttons service if display uses them
if [ "$BUTTONS" -eq "1" ]; then
    echo "###### Spotipi-eink button action service installation"
    if [ -f "/etc/systemd/system/spotipi-eink-buttons.service" ]; then
        echo
        echo "Removing old spotipi-eink-buttons service:"
        sudo systemctl stop spotipi-eink-buttons
        sudo systemctl disable spotipi-eink-buttons
        sudo rm -rf /etc/systemd/system/spotipi-eink-buttons.*
        sudo systemctl daemon-reload
        echo "...done"
    fi
    echo
    echo "Creating spotipi-eink-buttons service:"
    sudo cp "${install_path}/setup/service_template/spotipi-eink-buttons.service" /etc/systemd/system/
    sudo sed -i -e "/\[Service\]/a ExecStart=${install_path}/spotipienv/bin/python3 ${install_path}/python/buttonActions.py" /etc/systemd/system/spotipi-eink-buttons.service
    sudo sed -i -e "/ExecStart/a WorkingDirectory=${install_path}" /etc/systemd/system/spotipi-eink-buttons.service
    sudo sed -i -e "/EnvironmentFile/a User=${UID_TO_USE}" /etc/systemd/system/spotipi-eink-buttons.service
    sudo sed -i -e "/User/a Group=${GID_TO_USE}" /etc/systemd/system/spotipi-eink-buttons.service
    sudo mkdir /etc/systemd/system/spotipi-eink-buttons.service.d
    spotipi_buttons_env_path=/etc/systemd/system/spotipi-eink-buttons.service.d/spotipi-eink-buttons_env.conf
    sudo touch "$spotipi_buttons_env_path"
    echo "[Service]" | sudo tee -a "$spotipi_buttons_env_path" > /dev/null
    echo "Environment=\"SPOTIPY_CLIENT_ID=${spotify_client_id}\""       | sudo tee -a "$spotipi_buttons_env_path" > /dev/null
    echo "Environment=\"SPOTIPY_CLIENT_SECRET=${spotify_client_secret}\"" | sudo tee -a "$spotipi_buttons_env_path" > /dev/null
    echo "Environment=\"SPOTIPY_REDIRECT_URI=${spotify_redirect_uri}\""   | sudo tee -a "$spotipi_buttons_env_path" > /dev/null
    sudo systemctl daemon-reload
    sudo systemctl start spotipi-eink-buttons
    sudo systemctl enable spotipi-eink-buttons
    echo "...done"
else
    echo "###### Skipping Spotipi-eink button action service installation (BUTTONS=0)"
fi

echo
echo "SETUP IS COMPLETE"
