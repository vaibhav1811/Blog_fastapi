import uuid # for generating unique filenames
from io import BytesIO # for handling in-memory file operations
from pathlib import Path # for handling file paths

from PIL import Image,ImageOps # for image processing, including opening, resizing, and saving images

# Base directory for media files and profile pictures directory
BASE_DIR = Path(__file__).resolve().parent
PROFILE_PICS_DIR = BASE_DIR / "media" / "profile_pics"

# so our fastapi is currently asynchronous, but PIL is not, so we need to run the image processing in a separate thread to avoid blocking the event loop
# so solution fo that is use run in threadpool executor, which allows us to run blocking code in a separate thread without blocking the main event loop

## Process Image Function
def process_profile_image(content: bytes) -> str:
    with Image.open(BytesIO(content)) as original:
        img = ImageOps.exif_transpose(original) # correct orientation based on EXIF data

        img = ImageOps.fit(img, (300, 300), method=Image.Resampling.LANCZOS) # resize and crop to 300x300 using high-quality resampling

        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        filename = f"{uuid.uuid4().hex}.jpg" # generate a unique filename using UUID
        filepath = PROFILE_PICS_DIR/filename # construct the full file path for saving the image

        PROFILE_PICS_DIR.mkdir(parents=True, exist_ok=True) # ensure the directory exists

        img.save(filepath, "JPEG", quality=85, optimize=True) # save the image as JPEG with quality and optimization

    return filename


## Delete Profile Image Function
def delete_profile_image(filename: str | None) -> None:
    if filename is None:
        return

    filepath = PROFILE_PICS_DIR / filename
    if filepath.exists():
        filepath.unlink() #pathlib method to delete the file