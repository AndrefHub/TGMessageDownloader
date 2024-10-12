import argparse
import configparser
import asyncio
from TelegramDownloader import MessageDownloader


def convert_to_number_if_possible(a, just_try=True):
    try:
        return int(a)
    except Exception:
        try:
            return float(a)
        except Exception:
            try:
                return int(a, 16)
            except Exception:
                if just_try:
                    return a
                else:
                    raise


def number_config(config):
    ret_cfg = {}
    for sk, sv in config._sections.items():
        ret_cfg[sk] = {k: convert_to_number_if_possible(v) for k, v in sv.items()}
    return ret_cfg


def load_arguments():
    parser = argparse.ArgumentParser(description="Load credentials from .ini file.")
    parser.add_argument("-c", "--config", help="Path to the .ini configuration file")
    parser.add_argument(
        "-d",
        "--dry",
        action="store_true",
        help="Run the script without making any calls to API",
    )
    args = parser.parse_args()
    return args


def load_config(filename):
    config = configparser.ConfigParser()
    config.read(filename)
    return config


def get_config_from_arguments(args):
    if args.config:
        return load_config(args.config)
    return None


def overwrite_default_credentials(config: dict):
    if config:
        global api_id, api_hash, phone_number
        api_values = {
            key: config["API"].get(key)
            for key in ("api_id", "api_hash", "phone_number")
        }
        if all(api_values.values()):
            api_id, api_hash, phone_number = api_values.values()


async def main():
    try:
        args = load_arguments()
        config = get_config_from_arguments(args)
    except Exception as e:
        print(f"Failed to load config, exiting. Error message: {e}")
        exit()

    channel = convert_to_number_if_possible(config.get("info", "channel"))
    md = MessageDownloader(
        **config["tg"], **config["paths"], start_date=config["info"]["start_date"]
    )
    await md.get_history(channel)


if __name__ == "__main__":
    asyncio.run(main())
