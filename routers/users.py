## Imports for Users Router
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile,Query,BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from PIL import UnidentifiedImageError
from starlette.concurrency import run_in_threadpool # for running blocking code in a separate thread to avoid blocking the main event loop
from image_utils import process_profile_image, delete_profile_image,upload_profile_image

import models
from database import get_db
from schemas import PostResponse, UserCreate, UserPublic,UserPrivate, UserUpdate, Token , PaginatedPostsResponse,ChangePasswordRequest,ForgotPasswordRequest, ResetPasswordRequest

from datetime import timedelta, datetime, UTC

from fastapi.security import OAuth2PasswordRequestForm
from auth import (
    CurrentUser,
    create_access_token,
    hash_password,
    verify_password,
    generate_reset_token,
    hash_reset_token,
     )
from email_utils import send_password_reset_email
from config import settings
from botocore.exceptions import ClientError # for handling exceptions when interacting with AWS S3, such as when deleting a profile picture that may not exist in the S3 bucket. We can catch ClientError exceptions to handle cases where the file to be deleted is not found or there are issues with AWS credentials, allowing us to log the error and continue without crashing the application. This is important for maintaining robustness and ensuring that our application can gracefully handle errors related to S3 operations without affecting the user experience.


router = APIRouter()

## create_user
@router.post(
    "",  # the path is empty because we will use the prefix /users in the main.py file, so the full path for this endpoint will be /users
    response_model=UserPrivate,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(user: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(func.lower(models.User.username) == user.username.lower()),
    )

    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    result = await db.execute(
        select(models.User).where(func.lower(models.User.email) == user.email.lower()),
    )
    existing_email = result.scalars().first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    new_user = models.User(
        username=user.username,
        email=user.email.lower(),
        password_hash= hash_password(user.password),
    )

    db.add(new_user) # we didnt use await here because add is not an async method, it just adds the object to the session, it does not interact with the database until we commit the session, so we can use it without await. but commit and refresh are async methods because they interact with the database, so we need to use await with them.
    await db.commit()
    await db.refresh(new_user)
    return new_user


## login_for_access_token
@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Look up user by email (case-insensitive)
    # Note: OAuth2PasswordRequestForm uses "username" field, but we treat it as email
    result = await db.execute(
        select(models.User).where(
            func.lower(models.User.email) == form_data.username.lower(),
        ),
    )
    user = result.scalars().first()

    # Verify user exists and password is correct
    # Don't reveal which one failed (security best practice)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token with user id as subject
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )
    return Token(access_token=access_token, token_type="bearer")

## get_current_user
@router.get("/me", response_model=UserPrivate)
async def get_current_user(current_user: CurrentUser):
    return current_user


## forgot_password endpoint
@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED) # we use 202 Accepted because the request is accepted for processing, but the processing is not completed yet, since we are sending the email in the background, it may take some time to complete, so 202 is more appropriate than 200 OK which implies that the request has been processed successfully and the response is ready.
async def forgot_password(
    request_data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.User).where(
            func.lower(models.User.email) == request_data.email.lower(),
        ),
    )
    user = result.scalars().first()

    if user:
        await db.execute(
            sql_delete(models.PasswordResetToken).where(
                models.PasswordResetToken.user_id == user.id,
            ),
        )

        token = generate_reset_token()
        token_hash = hash_reset_token(token)
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.reset_token_expire_minutes
        )

        reset_token = models.PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(reset_token)
        await db.commit()

        #notice we are passing direct data as a string and not a db session object to the send_password_reset_email function, this is because we want to send the email in the background after the response is sent to the client, and we cannot pass the db session object to the background task because it is not thread-safe and will be closed after the request is completed. Instead, we pass the necessary data (email, username, token) as arguments to the background task, and the send_password_reset_email function can use this data to send the email without needing access to the db session. This allows us to send the email asynchronously without blocking the main event loop or risking issues with database connections in a multi-threaded environment.
        background_tasks.add_task(
            send_password_reset_email,
            to_email=user.email,
            username=user.username,
            token=token,
            # notice here that we are passing the unhashed token to the send_password_reset_email function, which will be included in the password reset link sent to the user's email. The hashed version of the token is stored in the database for security reasons, so that even if the database is compromised, attackers cannot use the token to reset the user's password. When the user clicks the link and submits a password reset request, we will hash the provided token and compare it with the stored hash in the database to verify its validity.
        )

    return {
        "message": "If an account exists with this email, you will receive password reset instructions."
    }
     # email enumeration attack prevention: we return the same response regardless of whether the email exists in our system or not, this way we don't reveal any information about which emails are registered in our system, making it more secure against attackers trying to find valid email addresses.


## reset_password endpoint
@router.post("/reset-password", status_code=status.HTTP_200_OK) # we use 200 OK here because if the reset is successful, we want to return a success message in the response body, and 200 OK is appropriate for indicating that the request was successful and the response contains the result of the operation. We don't use 204 No Content because we do want to return a message in the response body, and 204 implies that there is no content in the response.
async def reset_password(
    request_data: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    token_hash = hash_reset_token(request_data.token)

    result = await db.execute(
        select(models.PasswordResetToken).where(
            models.PasswordResetToken.token_hash == token_hash,
        ),
        # we are querying the database for the hashed version of the token, not the unhashed token, because we only store the hashed version in the database for security reasons. When the user submits a password reset request with the token they received in their email, we hash that token and compare it to the stored hash in the database to verify its validity. This way, even if someone gains access to the database, they cannot use the hashed tokens to reset passwords, since they cannot reverse the hash to get the original token value.
    )
    reset_token = result.scalars().first()
    # we check if the reset token exists and is valid (not expired) before allowing the password reset to proceed. If the token is invalid or expired, we return a 400 Bad Request response with an appropriate error message. This ensures that only valid password reset requests are processed, enhancing the security of the password reset functionality in our application.

    if not reset_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
            # we return the same error message for both invalid and expired tokens to avoid giving away information about which tokens are in the database, this way we prevent attackers from trying to guess valid tokens based on the error messages they receive.
        )

    if reset_token.expires_at < datetime.now(UTC): 
        await db.delete(reset_token)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    result = await db.execute(
        select(models.User).where(models.User.id == reset_token.user_id),
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    
    # if the token is valid and not expired, we proceed to reset the user's password by hashing the new password provided in the request and updating the user's password_hash field in the database. After updating the password, we delete all password reset tokens associated with that user to prevent reuse of any existing tokens, ensuring that once a password has been reset, any previously issued tokens are invalidated for security reasons. Finally, we commit the changes to the database and return a success message indicating that the password has been reset successfully.
    user.password_hash = hash_password(request_data.new_password)
    
    # we delete all password reset tokens for the user after a successful password reset to ensure that any existing tokens cannot be reused, enhancing the security of the password reset process by preventing potential misuse of old tokens that may have been compromised or are still valid.
    await db.execute(
        sql_delete(models.PasswordResetToken).where(
            models.PasswordResetToken.user_id == user.id,
        ),
    )

    await db.commit()
    return {
        "message": "Password reset successfully. You can now log in with your new password."
    }

## change_password endpoint
@router.patch("/me/password", status_code=status.HTTP_200_OK)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # we verify the current password provided by the user before allowing them to change their password. This is an important security measure to ensure that only the legitimate user can change their password, preventing unauthorized users who may have access to the user's session or token from changing the password without knowing the current password. If the current password is incorrect, we return a 400 Bad Request response with an appropriate error message, and if it is correct, we proceed to update the password as requested.
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(password_data.new_password)

    await db.execute(
        sql_delete(models.PasswordResetToken).where(
            models.PasswordResetToken.user_id == current_user.id,
        ),
    )

    await db.commit()
    return {"message": "Password changed successfully"}


## get_user
@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalars().first()
    if user:
        return user
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")



## get_user_posts - paginated
@router.get("/{user_id}/posts", response_model=PaginatedPostsResponse)
async def get_user_posts(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    count_result = await db.execute(
        select(func.count())
        .select_from(models.Post)
        .where(models.Post.user_id == user_id),
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.user_id == user_id)
        .order_by(models.Post.date_posted.desc())
        .offset(skip)
        .limit(limit),
    )
    posts = result.scalars().all()

    has_more = skip + len(posts) < total

    return PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts],
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )

## update_user
@router.patch("/{user_id}", response_model=UserPrivate)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user",
        )
    
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if user_update.username is not None and user_update.username.lower() != user.username.lower():
        result = await db.execute(
            select(models.User).where(func.lower(models.User.username) == user_update.username.lower()),
        )
        existing_user = result.scalars().first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )
    if user_update.email is not None and user_update.email.lower() != user.email.lower():
        result = await db.execute(
            select(models.User).where(func.lower(models.User.email) == user_update.email.lower()),
        )
        existing_email = result.scalars().first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    if user_update.username is not None:
        user.username = user_update.username
    if user_update.email is not None:
        user.email = user_update.email.lower()
   

    await db.commit()
    await db.refresh(user)
    return user




## delete_user
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int,current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    if user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user",
        )

    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    old_filename = user.image_file

    await db.delete(user) # we can use await here because delete is an async method in AsyncSession, it interacts with the database to mark the object for deletion, so we need to use await with it. but add is not an async method because it just adds the object to the session, it does not interact with the database until we commit the session, so we can use it without await.
    await db.commit()

    if old_filename: # if the user had a profile picture, we want to delete it from the server when the user is deleted to free up storage space and avoid orphaned files. We use the delete_profile_image function, which takes the old filename as an argument and deletes the corresponding file from the server. This ensures that we don't accumulate unused profile pictures on the server over time as users are deleted.
        await delete_profile_image(old_filename) #await here because delete_profile_image is an async function that interacts with the server to delete the file, so we need to use await with it to ensure that the file deletion is completed before the function returns. This way, we can handle any potential errors that may occur during the file deletion process and ensure that the user's profile picture is properly deleted from the server when their account is deleted.


    ## Upload Profile Picture Endpoint
@router.patch("/{user_id}/picture", response_model=UserPrivate)
async def upload_profile_picture(
    user_id: int,
    file: UploadFile, #UploadFile is a special type provided by FastAPI that represents an uploaded file. It provides attributes and methods to access the file's content, filename, content type, and other metadata. When you define a parameter as UploadFile in your endpoint function, FastAPI will automatically handle the file upload process and provide you with an instance of UploadFile that you can use to read the file's content and save it to your server or perform any necessary processing.
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user's picture",
        )

    content = await file.read() # we need to use await here because read is an async method of UploadFile, it reads the content of the uploaded file asynchronously, so we need to use await with it to get the content as bytes.

    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {settings.max_upload_size_bytes // (1024 * 1024)}MB",
        )

    try:
        processed_bytes,new_filename = await run_in_threadpool(process_profile_image, content) # we need to use run_in_threadpool here because process_profile_image is a blocking function that uses PIL for image processing, which is not asynchronous. By using run_in_threadpool, we can run the blocking code in a separate thread without blocking the main event loop of FastAPI, allowing other requests to be processed concurrently while the image is being processed.
    except UnidentifiedImageError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file. Please upload a valid image (JPEG, PNG, GIF, WebP).",
        ) from err
    
    
    # Upload to S3 (also runs in threadpool via async wrapper)
    try:
       await upload_profile_image(processed_bytes, new_filename)
    except ClientError as err:
     raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to upload image. Please try again.",
    ) from err


    old_filename = current_user.image_file

    current_user.image_file = new_filename # we update the user's image_file field with the new filename returned by the process_profile_image function, which is the name of the saved profile picture. This way, we can keep track of the current profile picture associated with the user in the database, and we can also use this filename to delete the old profile picture from the server if needed when a new one is uploaded.
    await db.commit()
    await db.refresh(current_user)

    if old_filename: # if there was an old profile picture, we want to delete it from the server to free up storage space and avoid orphaned files. We use the delete_profile_image function, which takes the old filename as an argument and deletes the corresponding file from the server. This ensures that we don't accumulate unused profile pictures on the server over time as users update their profile pictures.
        await delete_profile_image(old_filename)

    return current_user

## Delete Profile Picture Endpoint
@router.delete("/{user_id}/picture", response_model=UserPrivate)
async def delete_user_picture(
    user_id: int,
    current_user: CurrentUser, 
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user's picture",
        )

    old_filename = current_user.image_file

    if old_filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No profile picture to delete",
        )

    current_user.image_file = None
    await db.commit()
    await db.refresh(current_user)

    await delete_profile_image(old_filename)

    return current_user




