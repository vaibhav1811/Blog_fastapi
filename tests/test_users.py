from io import BytesIO
from pathlib import Path
from unittest.mock import patch,AsyncMock

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, create_test_user, login_user

## Test Create User Validation Error
@pytest.mark.anyio
async def test_create_user_validation_error(client: AsyncClient):
    response = await client.post(
        "/api/users",
        json={
            "username": "testuser",
        },
    )

    assert response.status_code == 422
    assert "email" in response.text
    assert "password" in response.text


## Test Create User Duplicate Email
@pytest.mark.anyio
async def test_create_user_duplicate_email(client: AsyncClient):
    await create_test_user(client)

    response = await client.post(
        "/api/users",
        json={
            "username": "different_user",
            "email": "test@example.com",
            "password": "password123",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"



## Test Create User Success
@pytest.mark.anyio
async def test_create_user_success(client: AsyncClient):
    response = await client.post(
        "/api/users",
        json={
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "securepassword123",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "newuser"
    assert data["email"] == "newuser@example.com"
    assert "id" in data
    assert "image_path" in data
    assert "password" not in data  # This helps ensure that the password is not returned in the response
    assert "password_hash" not in data   # This helps ensure that the password hash is not returned in the response


## Test Upload Profile Picture
@pytest.mark.anyio
async def test_upload_profile_picture(client: AsyncClient, mocked_aws):
    user = await create_test_user(client)
    token = await login_user(client)

    test_image_path = Path(__file__).parent / "test_image.jpg"  # this __file__ refers to the current test file, and we are looking for a test image in the same directory
    image_bytes = test_image_path.read_bytes()

    response = await client.patch(
        f"/api/users/{user['id']}/picture",
        files={"file": ("profile.jpg", BytesIO(image_bytes), "image/jpeg")},  # each of this tuple represents (filename, file-like object, content type),in details, we are sending a file named "profile.jpg" with the content of the image read from the test_image.jpg file, and specifying that it's a JPEG image 
        headers=auth_header(token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["image_file"] is not None
    assert data["image_file"].endswith(".jpg")
    assert "s3" in data["image_path"]

# Test that the image was uploaded to the mocked S3 bucket
    s3_objects = mocked_aws.list_objects_v2(Bucket="test-bucket")
    assert "Contents" in s3_objects
    assert len(s3_objects["Contents"]) == 1  # Check that there is exactly one object in the mocked S3 bucket
    assert s3_objects["Contents"][0]["Key"].endswith(data["image_file"])  # Check that the uploaded file's key in S3 matches the filename returned in the response


## Test Forgot Password Sends Email (background task testing)
@pytest.mark.anyio
async def test_forgot_password_sends_email(client: AsyncClient):
    await create_test_user(client)

    with patch(
        "routers.users.send_password_reset_email",  #This is the path to the function we want to mock. It allows us to replace the actual implementation of send_password_reset_email with a mock object during the test.
        new_callable=AsyncMock,  #This is used to mock the send_password_reset_email function, allowing us to test the forgot password functionality without actually sending an email
    ) as mock_send:
        response = await client.post(
            "/api/users/forgot-password",
            json={"email": "test@example.com"},
        )

        assert response.status_code == 202
        mock_send.assert_awaited_once()  # This checks that the mocked send_password_reset_email function was called exactly once during the test. If it was not called or was called more than once, this assertion will fail.
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["to_email"] == "test@example.com"
        assert call_kwargs["username"] == "testuser"
        assert "token" in call_kwargs