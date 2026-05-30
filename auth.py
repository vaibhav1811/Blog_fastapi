from datetime import UTC, datetime, timedelta
import jwt
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from config import settings

password_hash= PasswordHash.recommended() # PasswordHash is a class provided by the pwdlib library that offers various password hashing algorithms. The recommended() method returns an instance of the most secure and up-to-date password hashing algorithm available, which is currently bcrypt. By using password_hash, you can hash and verify passwords securely in your application.

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/users/token")
#OAuth2PasswordBearer is a class provided by FastAPI that implements the OAuth2 password flow. It is used to define the security scheme for authentication in your API. By specifying tokenUrl="api/users/token", you are indicating that the token endpoint for obtaining access tokens is located at "api/users/token". This allows FastAPI to handle the authentication process and validate the tokens when they are included in requests to protected endpoints.

def hash_password(password:str)->str:
    return password_hash.hash(password) #hash() method of the password_hash instance is used to hash a plain text password. It takes the password as input and returns the hashed version of it. This hashed password can then be stored securely in a database, and when a user attempts to log in, you can use the verify() method to check if the provided password matches the stored hash.

def verify_password(plain_password:str, hashed_password:str)->bool:
    return password_hash.verify(plain_password, hashed_password) #verify() method of the password_hash instance is used to verify if a plain text password matches a previously hashed password. It takes the plain text password and the hashed password as input and returns True if they match, or False if they do not. This is typically used during the login process to authenticate users by comparing the provided password with the stored hash in the database.

#we used hashing and not encryption because hashing is a one-way function that transforms the password into a fixed-length string of characters, which cannot be reversed back to the original password. This means that even if someone gains access to the hashed passwords, they cannot retrieve the original passwords. On the other hand, encryption is a two-way function that allows you to encrypt and decrypt data using a key. If we were to use encryption for passwords, it would require storing the encryption key securely, and if that key were compromised, all passwords could be decrypted. Hashing provides a more secure way to store passwords without the risk of exposing them in case of a data breach.

## create_access_token
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.access_token_expire_minutes,
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )
    return encoded_jwt

## verify_access_token
def verify_access_token(token: str) -> str | None:
    """Verify a JWT access token and return the subject (user id) if valid."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None
    else:
        return payload.get("sub")

