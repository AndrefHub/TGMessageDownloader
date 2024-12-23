import subprocess
import os
import time
from credentials import api_id, api_hash, phone
from cities import cities


# Define base path for configuration directories

root_path = "/var/www/TGMessageDownloader"
script_path = f"{root_path}/load_history.py"
base_config_path = "./conf.d/"
service_path = "/etc/systemd/system/"
# service_path = "./system/" # use for tests/checks


# Templates
config_template = """[tg]
api_id = {API_ID}
api_hash = {API_HASH}
phone = {PHONE}
bot_token = {BOT_TOKEN}

[paths]
url = http://localhost:{PORT}
create_url = ${{url}}/api/news/update
delete_url = ${{url}}/api/news/deleteByTGID
media_path = /var/www/media/{CITY}
image_path = ${{media_path}}/images
video_path = ${{media_path}}/videos
thumbnail_path = ${{media_path}}/thumbnails
fastimage_path = ${{media_path}}/fastimages

[info]
channel = {CHANNEL_ID}
start_date = 2024-12-01
; start_date = 2024-08-26
"""

service_template = """[Unit]
Description=BLM for {CITY}

[Service]
ExecStart=/var/www/TGMessageDownloader/env/bin/python /var/www/TGMessageDownloader/blm.py --config config.ini
WorkingDirectory=/var/www/TGMessageDownloader/conf.d/{CITY}
Restart=always
OOMScoreAdjust=-1000

[Install]
WantedBy=multi-user.target
"""


# Function to create config directories and service files
def create_configs():
    os.makedirs(base_config_path, exist_ok=True)
    os.makedirs(service_path, exist_ok=True)

    for data in cities:
        city, port, channel_id, bot_token = (
            data["city"],
            f'{data["port"]}',
            data["channel_id"],
            data["bot_token"],
        )

        # Create directory for each city
        city_dir = os.path.join(base_config_path, city)
        os.makedirs(city_dir, exist_ok=True)

        # Generate config content
        config_content = config_template.format(
            CITY=city, PORT=port, CHANNEL_ID=channel_id, BOT_TOKEN=bot_token,
            API_ID=api_id, API_HASH=api_hash, PHONE=phone
        )

        # Save config file in city's directory
        config_file_path = os.path.join(city_dir, "config.ini")
        with open(config_file_path, "w") as config_file:
            config_file.write(config_content)

        # Generate systemd service content
        service_content = service_template.format(CITY=city)

        # Save service file
        service_file_path = os.path.join(service_path, f"blm-{city}.service")
        with open(service_file_path, "w") as service_file:
            service_file.write(service_content)

        print(
            f"Created config file at {config_file_path} and service file at {service_file_path}"
        )

    # Command to run the load_history.py script in the background
    subprocess.Popen(["systemctl", "daemon-reload"])

def run_daemons():
    cmd = [
        "/var/www/TGMessageDownloader/env/bin/python",  # Path to the Python executable in your virtual environment
        script_path,  # Path to the load_history.py script
        "--config",
        "config.ini",  # Passing the config file as an argument
    ]
    # Iterate through each city
    for data in cities:
        city = data["city"]
        city_dir = os.path.join(base_config_path, city)

        try:
            # Каждый город обрабатывается по очереди,
            # т.к. если скачивать сразу 10 городов с 1 аккаунта,
            # может отьебнуть тг аккаунт, а я в бане сидеть не хочу :)
            subprocess.run(["systemctl", "enable", f"blm-{city}"])
            subprocess.run(["systemctl", "start", f"blm-{city}"])
            print(f"Started downloading news for {city}.")
            subprocess.run(cmd, cwd=city_dir)

        except Exception as e:
            print(f"Failed to start process for {city}: {e}")
        
        time.sleep(5)


# Run the function
if __name__ == "__main__":
    create_configs()
    # run_daemons()

