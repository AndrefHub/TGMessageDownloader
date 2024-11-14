import argparse
import configparser
import asyncio
import logging

from TelegramDownloader import MessageDownloader
import tgutils

logger = logging.getLogger(__name__)

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

def configure_logger(log_folder="logs"):
    tgutils.create_output_directories(log_folder)
    logging.basicConfig(
        # filename=f"{log_folder}/telegram_dler.log",
        level=logging.INFO,
        format="%(asctime)s - %(name)-25s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(f"{log_folder}/telegram_blm.log"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)


async def main():
    configure_logger()
    try:
        args = load_arguments()
        config = get_config_from_arguments(args)
    except Exception as e:
        print(f"Failed to load config, exiting. Error message: {e}")
        exit()

    channel = convert_to_number_if_possible(config.get("info", "channel"))
    md = MessageDownloader(
        **config["tg"],
        **config["paths"],
        start_date=config["info"]["start_date"],
        dry=args.dry,
    )
    while True:
        try:
            await md.get_new_messages(channel)
        except Exception:
            logger.exception("message")
        finally:
            logger.info("Restarting BLM")


if __name__ == "__main__":
    asyncio.run(main())
