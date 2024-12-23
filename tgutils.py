import os
import json
import re
import asyncio
import aiohttp
import pathlib
import logging
import decord
import PIL
import emoji
import codecs

logger = logging.getLogger(__name__)


def create_output_directories(*args):
    for path in args:
        os.makedirs(path, exist_ok=True)


def write_messages_to_file(messages, filename):
    with codecs.open(filename, "w", "utf-8") as f:
        json.dump(messages, f, ensure_ascii=False)


# Функция для проверки хэштегов с форматированием
def has_valid_hashtag(text: str, hashtags: list[str]):
    formatted_text = re.sub(
        r"[*_~]", "", text
    )  # Убираем форматирование (курсив, жирный и т.д.)
    return any(hashtag in formatted_text for hashtag in hashtags)


def check_message_text_for_hashtags(text: str, hashtags: list[str]):
    if text:
        # logger.warn(text)
        return has_valid_hashtag(text, hashtags)
    # skipping check for messages with no text
    # because they are highly likely grouped media
    return True


def convert_message_to_data(message):
    return {
        "groupID": message.group_id or message.id,
        "date": message.date,
        "text": message.text or "",
        "media": [message.media],
    }


def convert_group_to_data(group):
    return {
        "groupID": group[0].group_id,
        "date": next(
            message.date for message in group if message.date
        ),  # get first available date if first message don't have one
        "text": next((message.text for message in group if message.text), ""),
        "media": [message.media for message in group if message.media],
    }


async def send_to_api(url, data):
    origin = "https://topsmi.ru/"
    logger.debug(f"Sending {data} to {url}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.put(
                url, json=data, headers={"origin": origin}
            ) as response:
                if response.ok:
                    logger.info(f"Message successfully sent to Next.js API: {data}")
                else:
                    logger.warn(
                        f"Failed to send message '{data}': {response.status}, {await response.text()}"
                    )
        except Exception as e:
            logger.warn(f"Error sending message to API: {e}. Data: {data}")


async def delete_news(url, message_id):
    origin = "https://topsmi.ru/"
    logger.debug(f"Sending delete to {url} with {message_id}")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.delete(
                url, params={"messageId": message_id}, headers={"origin": origin}
            ) as response:
                if response.ok:
                    logger.info(
                        f"Deletion successfully sent to Next.js API: {message_id}"
                    )
                else:
                    logger.warn(
                        f"Failed to send message: {response.status}, {await response.text()}"
                    )
        except Exception as e:
            logger.warn(f"Error sending message to API: {e}. Data: {message_id}")


def is_media_downloaded(message_id, *paths):
    for path in paths:
        files = list(pathlib.Path(path).glob(f"{message_id}.*"))
        if files:
            return files
    return []


def extract_frame(video_path, output_image_path, frame_number=0):
    # Load the video with decord
    video_reader = decord.VideoReader(video_path, ctx=decord.cpu(0))

    # Get a specific frame (0 for the first frame)
    frame = video_reader[frame_number]

    # Convert frame to a PIL Image and save as JPEG
    image = PIL.Image.fromarray(frame.asnumpy())
    image.save(output_image_path)


# Function to preserve hashtags within markdown
def preserve_hashtags(match):
    content = match.group(0)  # Get the full matched text
    hashtags = re.findall(r"#\w+", content)  # Find hashtags inside the matched text
    return " ".join(hashtags)  # Return only the hashtags


# Function to remove italic text but preserve hashtags
def remove_italics(text):
    # return re.sub(r"__.*?__", preserve_hashtags, text, flags=re.DOTALL)
    return text.replace("__", "")


def remove_bold(text):
    # Use a regular expression to remove double asterisks used for bold formatting
    # return re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    return text.replace("**", "")


# Function to remove emojis
def remove_emojis(text):
    return emoji.replace_emoji(text)


# Function to remove all text after the last valid hashtag
def remove_after_last_valid_hashtag(text, hashtags):
    index = -1
    last_valid_hashtag_position = -1
    for i in range(len(hashtags)):
        position = text.rfind(hashtags[i])
        if position != -1 and last_valid_hashtag_position < position:
            last_valid_hashtag_position = position
            index = i
    if last_valid_hashtag_position != -1:
        text = text[: last_valid_hashtag_position + len(hashtags[index])]
    return text

# Function to remove all text after the first valid hashtag
# while preserving all hashtags
def remove_after_first_valid_hashtag(text, hashtags):
    text_hashtags = []
    first_valid_hashtag_position = len(text)
    for hashtag in hashtags:
        position = text.rfind(hashtag)
        if position != -1:
            text_hashtags.append(hashtag)
            if position < first_valid_hashtag_position:
                first_valid_hashtag_position = position
    if first_valid_hashtag_position != len(text):
        text = text[:first_valid_hashtag_position] + " ".join(text_hashtags)
    return text


# Main function to clean up the text using all three steps
def cleanup_text(text, hashtags=None):
    # valid_hashtags = get_valid_hashtags(text, hashtags)
    text = remove_italics(text) # Remove italic text
    text = remove_bold(text)    # Remove bold text
    text = remove_emojis(text)  # Remove emojis
    if hashtags:
        text = remove_after_first_valid_hashtag(text, hashtags)
    text = text.strip()
    # for hashtag
    return text


def cleanup_text_in_json(message, hashtags=None):
    message["text"] = cleanup_text(message["text"], hashtags)
    return message


def change_filename_preserve_ext(new_name, old_path):
    _, ext = os.path.splitext(old_path)
    media_filename = f"{new_name}{ext}"
    return media_filename


def generate_new_file_path(dest_dir, filename, new_extension="webp"):
    """Generate a new file path by combining directory, filename, and new extension."""
    filename_without_ext = os.path.splitext(os.path.basename(filename))[0]
    return os.path.join(dest_dir, f"{filename_without_ext}.{new_extension}")


def compress_thumbnail(image_path, new_file_path, quality=50, width=300):
    """Compress an image as a thumbnail and save it with the given new file path."""
    img = PIL.Image.open(image_path)
    height = int((width / img.size[0]) * img.size[1])
    img = img.resize((width, height), resample=PIL.Image.LANCZOS)

    # Change the extension to .webp in the new file path
    new_file_path = os.path.splitext(new_file_path)[0] + ".webp"

    try:
        img.save(new_file_path, quality=quality, optimize=True)
    except OSError:
        img = img.convert("RGB")
        img.save(new_file_path, quality=quality, optimize=True)
    finally:
        img.close()

    return new_file_path


def compress_image(image_path, new_file_path, ratio=0.5, quality=50):
    """Compress an image by scaling it and save it with the given new file path."""
    img = PIL.Image.open(image_path)
    img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)), resample=PIL.Image.LANCZOS)

    # Change the extension to .webp in the new file path
    new_file_path = os.path.splitext(new_file_path)[0] + ".webp"

    try:
        img.save(new_file_path, quality=quality, optimize=True)
    except OSError:
        img = img.convert("RGB")
        img.save(new_file_path, quality=quality, optimize=True)
    finally:
        img.close()

    return new_file_path