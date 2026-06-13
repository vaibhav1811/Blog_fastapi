import uuid # for generating unique filenames
from io import BytesIO # for handling in-memory file operations
#from pathlib import Path # for handling file paths

import boto3 # for interacting with AWS S3, if we were to use S3 for storage instead of local filesystem

from starlette.concurrency import run_in_threadpool # for running blocking code in a separate thread to avoid blocking the event loop
from PIL import Image,ImageOps # for image processing, including opening, resizing, and saving images
from config import settings # for accessing configuration settings, such as AWS credentials and S3 bucket name


## _get_s3_client helper for image_utils.py
def _get_s3_client():
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        aws_access_key_id=(
            settings.s3_access_key_id.get_secret_value()
            if settings.s3_access_key_id
            else None
        ),
        aws_secret_access_key=(
            settings.s3_secret_access_key.get_secret_value()
            if settings.s3_secret_access_key
            else None
        ),
        endpoint_url=settings.s3_endpoint_url,
    )


# Base directory for media files and profile pictures directory
#BASE_DIR = Path(__file__).resolve().parent
#PROFILE_PICS_DIR = BASE_DIR / "media" / "profile_pics"

# so our fastapi is currently asynchronous, but PIL is not, so we need to run the image processing in a separate thread to avoid blocking the event loop
# so solution fo that is use run in threadpool executor, which allows us to run blocking code in a separate thread without blocking the main event loop

## Process Image Function
def process_profile_image(content: bytes) -> tuple[bytes, str]:
    with Image.open(BytesIO(content)) as original:
        img = ImageOps.exif_transpose(original) # correct orientation based on EXIF data

        img = ImageOps.fit(img, (300, 300), method=Image.Resampling.LANCZOS) # resize and crop to 300x300 using high-quality resampling

        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        filename = f"{uuid.uuid4().hex}.jpg" # generate a unique filename using 
        
        output = BytesIO()  # create an in-memory bytes buffer to save the processed image

        
        img.save(output, "JPEG", quality=85, optimize=True) # save the image as JPEG with quality and optimization
        output.seek(0) # reset the buffer position to the beginning after writing

    return output.read(), filename # return the processed image content and the generated filename


## _upload_to_s3 and _delete_from_s3 for image_utils.py
def _upload_to_s3(file_bytes: bytes, key: str) -> None:
    s3 = _get_s3_client()
    s3.upload_fileobj(
        BytesIO(file_bytes),
        settings.s3_bucket_name,
        key,
        ExtraArgs={"ContentType": "image/jpeg"}, # set the content type to image/jpeg for proper handling in S3
    )


def _delete_from_s3(key: str) -> None:
    s3 = _get_s3_client()
    s3.delete_object(Bucket=settings.s3_bucket_name, Key=key)



## Async S3 wrappers for image_utils.py
#this function is responsible for uploading the processed profile image to S3. It takes the file bytes and the filename as arguments, constructs the S3 key by prefixing it with "profile_pics/", and then calls the _upload_to_s3 function in a separate thread using run_in_threadpool to avoid blocking the event loop.
async def upload_profile_image(file_bytes: bytes, filename: str) -> None:
    key = f"profile_pics/{filename}"
    await run_in_threadpool(_upload_to_s3, file_bytes, key)


async def delete_profile_image(filename: str | None) -> None:
    if filename is None:
        return
    key = f"profile_pics/{filename}"
    await run_in_threadpool(_delete_from_s3, key)