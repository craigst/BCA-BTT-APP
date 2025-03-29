import os
import sys
import time
import configparser
import logging
import base64
from datetime import datetime, timedelta
import pyinsane2
from PIL import Image, ImageOps, ImageFilter
import openai
from openai import OpenAI

# Directories
CONFIG_DIR = os.path.join("config")
SCANNED_DIR = "scanned"
EMAIL_DIR = os.path.join("email")
for d in [CONFIG_DIR, SCANNED_DIR, EMAIL_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# Setup simple logging to console.
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("scanner_app")
logging.getLogger("pyinsane2").setLevel(logging.WARNING)

# Global receipt counter.
receipt_counter = 1

def find_openai_ini():
    """
    Search for openai.ini in several possible paths.
    """
    possible_paths = [
        "/config/openai.ini",
        os.path.join(".", "config", "openai.ini"),
        os.path.join("config", "openai.ini")
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p
    # If not found, return default path in CONFIG_DIR.
    return os.path.join(CONFIG_DIR, "openai.ini")

def load_openai_settings():
    """
    Loads OpenAI settings from openai.ini.
    Returns a configparser object and the ini file path.
    """
    ini_path = find_openai_ini()
    config = configparser.ConfigParser()
    if os.path.exists(ini_path):
        config.read(ini_path)
    else:
        config["openai"] = {}
    return config, ini_path

def save_openai_settings(config, ini_path):
    """
    Save the given config object to ini_path.
    """
    with open(ini_path, "w", encoding="utf-8") as f:
        config.write(f)

def load_openai_api_key():
    config, ini_path = load_openai_settings()
    try:
        return config["openai"]["api_key"]
    except KeyError:
        logger.info("No API key found in %s", ini_path)
        return None

def get_vision_model():
    """
    Loads the vision model from the ini file if present.
    Otherwise, asks the user to select one from a hardcoded list,
    saves the selection to the ini file, and returns the chosen model.
    """
    config, ini_path = load_openai_settings()
    if "openai" not in config:
        config["openai"] = {}
    if "vision_model" in config["openai"]:
        vision_model = config["openai"]["vision_model"]
        logger.info("Using saved vision model: %s", vision_model)
        return vision_model
    else:
        available_models = ["gpt-4-vision-preview", "gpt-4-vision-alpha", "gpt-4o-mini"]
        logger.info("Available vision models:")
        for idx, model in enumerate(available_models, start=1):
            logger.info("%d) %s", idx, model)
        selection = input("Select a vision model by number: ").strip()
        try:
            sel_index = int(selection) - 1
            if sel_index < 0 or sel_index >= len(available_models):
                raise ValueError
            chosen_model = available_models[sel_index]
        except ValueError:
            logger.info("Invalid selection. Defaulting to %s", available_models[0])
            chosen_model = available_models[0]
        config["openai"]["vision_model"] = chosen_model
        save_openai_settings(config, find_openai_ini())
        logger.info("Saved vision model '%s' to %s", chosen_model, find_openai_ini())
        return chosen_model

def init_openai():
    """
    Initialize OpenAI by loading the API key and vision model.
    Exits if no API key is found.
    Returns the selected vision model.
    """
    api_key = load_openai_api_key()
    if not api_key:
        logger.info("OpenAI API key not found. Exiting.")
        sys.exit(1)
    # Explicitly set the API key for the client.
    openai.api_key = api_key
    vision_model = get_vision_model()
    logger.info("OpenAI settings loaded successfully.")
    return vision_model

def connect_scanner(retry_interval=10):
    """
    Continuously try to connect to a scanner until one is found.
    """
    logger.info("Connecting to scanner...")
    pyinsane2.init()
    scanner = None
    while scanner is None:
        devices = pyinsane2.get_devices()
        if devices:
            scanner = devices[0]
            logger.info("Connected to scanner: %s", scanner.name)
        else:
            logger.info("No scanner found. Retrying in %d seconds...", retry_interval)
            time.sleep(retry_interval)
    return scanner

def set_option(scanner, option, values):
    """
    Attempt to set a scanner option with error handling.
    """
    try:
        pyinsane2.set_scanner_opt(scanner, option, values)
        logger.info("Setting '%s' to %s", option, values)
    except Exception as e:
        logger.info("Failed to set '%s': %s", option, e)

def process_image(img):
    """
    Process the scanned image:
      1. Convert to grayscale and apply autocontrast.
      2. Binarize using a threshold.
      3. Invert the image and compute its bounding box.
      4. Crop to that bounding box.
      5. Apply a sharpening filter.
      6. Re-binarize for a crisp black-and-white result.
    Returns the processed (cropped) image.
    """
    gray = img.convert("L")
    enhanced = ImageOps.autocontrast(gray)
    bw = enhanced.point(lambda x: 0 if x < 128 else 255, mode="1")
    inverted = ImageOps.invert(bw.convert("L"))
    bbox = inverted.getbbox()
    if bbox:
        cropped = enhanced.crop(bbox)
    else:
        cropped = enhanced
    sharpened = cropped.filter(ImageFilter.SHARPEN)
    final = sharpened.point(lambda x: 0 if x < 128 else 255, mode="1")
    return final

def encode_image_to_base64(image_path):
    """
    Reads an image file and returns a Base64-encoded data URL string.
    """
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    b64_str = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"

def extract_date_from_image(image_path, vision_model):
    """
    Use the ChatGPT Vision model to extract the receipt date.
    The message includes a text prompt and an image object (encoded as a Base64 data URL)
    with detail level set to "high". The assistant is instructed to return only the date
    in DD-MM-YYYY format.
    """
    try:
        data_url = encode_image_to_base64(image_path)
        client = OpenAI(api_key=openai.api_key)  # Pass the API key explicitly
        response = client.chat.completions.create(
            model=vision_model,
            messages=[
                {"role": "system", "content": "You are an assistant that extracts dates from receipt images."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extract the exact date printed on this receipt in DD-MM-YYYY format. Return only the date."},
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}}
                ]}
            ],
            max_tokens=50,
        )
        result = response.choices[0].message.content.strip()
        logger.info("AI extracted date: %s", result)
        return result if result else "Unknown"
    except Exception as e:
        logger.info("Error during AI extraction: %s", e)
        return "Unknown"

def compute_sunday(receipt_date_str):
    """
    Given a receipt date string in "DD-MM-YYYY" format, compute the corresponding Sunday (end-of-work-week).
    Returns the Sunday date as a string in "DD-MM-YYYY" format.
    """
    try:
        receipt_date = datetime.strptime(receipt_date_str, "%d-%m-%Y").date()
    except Exception as e:
        logger.info("Error parsing receipt date '%s': %s", receipt_date_str, e)
        return None
    days_to_sunday = 6 - receipt_date.weekday()
    sunday_date = receipt_date + timedelta(days=days_to_sunday)
    return sunday_date.strftime("%d-%m-%Y")

def unique_target_path(target_path):
    """
    If target_path exists, append a timestamp suffix to create a unique filename.
    """
    base, ext = os.path.splitext(target_path)
    while os.path.exists(target_path):
        suffix = datetime.now().strftime("-%H%M%S")
        target_path = f"{base}{suffix}{ext}"
    return target_path

def scan_for_60s(scanner):
    """
    Scan repeatedly for up to 60 seconds, checking every 5 seconds.
    Each finished page is processed (cropped) and saved as a PNG in SCANNED_DIR.
    Returns a list of paths to the saved images.
    """
    logger.info("Starting scanning loop for 60 seconds (checking every 5 seconds).")
    scanned_images = []
    start_time = time.time()
    global receipt_counter

    while time.time() - start_time < 60:
        try:
            scan_session = scanner.scan(multiple=False)
        except Exception as e:
            logger.info("Could not start scan session: %s", e)
            time.sleep(5)
            continue

        page_scanned = False
        inner_start = time.time()
        while time.time() - inner_start < 5:
            try:
                scan_session.scan.read()
            except EOFError:
                if scan_session.images and len(scan_session.images) == 1 and not page_scanned:
                    raw_img = scan_session.images[0]
                    processed_img = process_image(raw_img)
                    png_filename = f"receipt{receipt_counter}.png"
                    full_path = os.path.join(SCANNED_DIR, png_filename)
                    processed_img.save(full_path, format="PNG")
                    logger.info("Scanned and cropped image saved as '%s'", full_path)
                    scanned_images.append(full_path)
                    receipt_counter += 1
                    page_scanned = True
                break
            except StopIteration:
                break
            except Exception as e:
                logger.info("Scanning error: %s", e)
                break
        if not page_scanned:
            logger.info("No page detected in this attempt. Retrying in 5 seconds.")
        time.sleep(5)
    logger.info("Finished scanning loop (60 seconds reached).")
    return scanned_images

def main():
    vision_model = init_openai()
    try:
        scanner = connect_scanner()
        set_option(scanner, 'source', ['ADF Duplex', 'ADF', 'Feeder'])
        set_option(scanner, 'mode', ['Color'])
        set_option(scanner, 'resolution', [300])  # Adjust dpi if needed
        try:
            pyinsane2.maximize_scan_area(scanner)
        except Exception as e:
            logger.info("Could not maximize scan area: %s", e)

        logger.info("Scanner is ready. Beginning scanning for 60 seconds.")
        scanned_paths = scan_for_60s(scanner)

        if scanned_paths:
            logger.info("Scanning complete. Processing scanned images for date extraction...")
            for path in scanned_paths:
                receipt_date = extract_date_from_image(path, vision_model)
                logger.info("Extracted receipt date: %s", receipt_date)
                sunday_date = compute_sunday(receipt_date)
                if not sunday_date:
                    sunday_date = "unknown"
                target_folder = os.path.join("email", sunday_date)
                if not os.path.exists(target_folder):
                    os.makedirs(target_folder)
                new_filename = f"Receipt-{receipt_date}.png"
                target_path = os.path.join(target_folder, new_filename)
                target_path = unique_target_path(target_path)
                os.rename(path, target_path)
                logger.info("Moved image to '%s'", target_path)
        else:
            logger.info("No images were scanned in this session.")

    except KeyboardInterrupt:
        logger.info("Exiting scanner application (KeyboardInterrupt).")
    except Exception as e:
        logger.info("Unexpected error: %s", e)
    finally:
        try:
            pyinsane2.exit()
        except Exception as e:
            logger.info("Error closing scanner interface: %s", e)
        logger.info("Exiting application.")

if __name__ == '__main__':
    main()
