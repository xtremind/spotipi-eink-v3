#!/bin/bash
if [[ $EUID -eq 0 ]]; then
  echo "This script must NOT be run as root" 1>&2
  exit 1
fi
echo "###### Update Packages list"
sudo apt update
echo
echo "###### Update to the latest"
sudo apt upgrade -y
echo
echo "###### Ensure system packages are installed:"
sudo apt-get install python3-pip python3-venv python3-numpy git libopenjp2-7 libjpeg-dev -y
echo
echo "###### Enabling SPI"
sudo raspi-config nonint do_spi 0
echo "...done"
echo

echo "###### Enabling I2C"
sudo raspi-config nonint do_i2c 0
echo "...done"
echo

if [ -d "spotipi-eink" ]; then
    echo "Old installation found deleting it"
    sudo rm -rf spotipi-eink
fi
if [ -d "spotipi-eink" ]; then
    echo "Old installation found deleting it"
    sudo rm -rf spotipi-eink
fi
echo
echo "###### Clone spotipy-eink git"
git clone https://github.com/Canterrain/spotipi-eink
echo "Switching into instalation directory"
cd spotipi-eink
install_path=$(pwd)
echo
echo "##### Creating Spotipi Python environment"
python3 -m venv --system-site-packages spotipienv
echo "Activating Spotipi Python environment"
source ${install_path}/spotipienv/bin/activate
echo Install Python packages: spotipy, pillow, requests, inky impression
pip3 install -r requirements.txt --upgrade
echo "##### Spotipi Python environment created" 
echo
echo "###### Generate Spotify Token"
if ! [ -d "${install_path}/config" ]; then
    echo "creating  ${install_path}/config path"
    mkdir -p "${install_path}/config"
fi
# Ensure idle_images directory exists
mkdir -p "${install_path}/config/idle_images"
# Ensure eink_options.ini exists with default settings
EINK_CONFIG_FILE="${install_path}/config/eink_options.ini"
if [ ! -f "$EINK_CONFIG_FILE" ]; then
if [ ! -f "$EINK_CONFIG_FILE" ]; then
    cat <<EOL > "$EINK_CONFIG_FILE"
[DEFAULT]
# Options: static, cycle
idle_mode = cycle
# Time to display each image in seconds (default: 5 minutes)
idle_display_time = 300
# If true, images will be displayed in random order
idle_shuffle = false
no_song_cover = ${install_path}/resources/default.jpg
EOL
fi
