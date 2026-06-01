from pydantic import SecretStr
from pydantic_settings import BaseSettings,SettingsConfigDict


class Settings(BaseSettings): #pydantic_settings.BaseSettings is a subclass of pydantic.BaseModel that provides additional functionality for loading settings from environment variables and .env files. It allows you to define your settings as a class with attributes, and it will automatically load the values from the specified sources.
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8"
        )
    
    secret_key: SecretStr #SecretStr is a special type provided by Pydantic that is used to handle sensitive information, such as passwords or API keys. When you define an attribute as SecretStr, Pydantic will automatically mask the value when it is printed or logged, and it will also provide a method to retrieve the original value when needed.
    algorithm: str = "HS256" #HS256 is a commonly used algorithm for signing JSON Web Tokens (JWTs). It stands for HMAC with SHA-256, which is a symmetric key algorithm that uses a secret key to both sign and verify the token. When you specify the algorithm as "HS256", it indicates that you want to use this algorithm for generating and validating JWTs in your application.
    access_token_expire_minutes: int = 30
     
    max_upload_size_bytes: int = 5 * 1024 * 1024 # 5 MB in bytes
    allowed_image_formats: set[str] = {"JPEG", "PNG", "GIF"} #allowed image formats for profile pictures, defined as a set of strings. This allows you to specify which image formats are acceptable for uploading profile pictures in your application. In this case, the allowed formats are JPEG, PNG, and GIF.
     
    post_per_page: int = 10 #number of posts to display per page in the pagination of the home page and user posts page. This setting can be used to control how many posts are shown on each page when displaying lists of posts in your application, allowing you to manage the amount of content displayed at once and improve the user experience when navigating through posts.
    
settings = Settings() #loaded from .env file