from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings): #pydantic_settings.BaseSettings is a subclass of pydantic.BaseModel that provides additional functionality for loading settings from environment variables and .env files. It allows you to define your settings as a class with attributes, and it will automatically load the values from the specified sources.
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8"
        )
    
    database_url: str

    secret_key: SecretStr #SecretStr is a special type provided by Pydantic that is used to handle sensitive information, such as passwords or API keys. When you define an attribute as SecretStr, Pydantic will automatically mask the value when it is printed or logged, and it will also provide a method to retrieve the original value when needed.
    algorithm: str = "HS256" #HS256 is a commonly used algorithm for signing JSON Web Tokens (JWTs). It stands for HMAC with SHA-256, which is a symmetric key algorithm that uses a secret key to both sign and verify the token. When you specify the algorithm as "HS256", it indicates that you want to use this algorithm for generating and validating JWTs in your application.
    access_token_expire_minutes: int = 60

        ## S3 Settings for config.py
    # S3 Configuration
    s3_bucket_name: str
    s3_region: str = "eu-north-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_endpoint_url: str | None = None
     
    max_upload_size_bytes: int = 5 * 1024 * 1024 # 5 MB in bytes
    allowed_image_formats: set[str] = {"JPEG", "PNG", "GIF"} #allowed image formats for profile pictures, defined as a set of strings. This allows you to specify which image formats are acceptable for uploading profile pictures in your application. In this case, the allowed formats are JPEG, PNG, and GIF.
     
    post_per_page: int = 10 #number of posts to display per page in the pagination of the home page and user posts page. This setting can be used to control how many posts are shown on each page when displaying lists of posts in your application, allowing you to manage the amount of content displayed at once and improve the user experience when navigating through posts.

    reset_token_expire_minutes: int = 30  #number of minutes before a password reset token expires. This setting can be used to control the validity period of password reset tokens in your application, ensuring that they are only valid for a limited time to enhance security and prevent unauthorized access to user accounts through expired tokens.
    ## Email Configuration Settings
    mail_server: str = "localhost"
    mail_port: int = 587
    mail_username: str = ""
    mail_password: SecretStr = SecretStr("")
    mail_from: str = "noreply@example.com"
    mail_use_tls: bool = True
    brevo_api_key: SecretStr | None = None
    resend_api_key: SecretStr | None = None

    frontend_url: str = "http://localhost:8000"

    # ── Environment & Docs Access ────────────────────────────────────────────
    # Set APP_ENV=production in your hosting platform to hide Swagger/ReDoc.
    # Accepted values: "development", "production"
    app_env: str = "development"

    # Comma-separated list of IP addresses that may access /docs and /redoc
    # even in production (e.g. your team's static IPs or VPN exit IP).
    # Example: DOCS_ALLOWED_IPS=203.0.113.10,198.51.100.5
    # Leave empty to block docs for everyone in production.
    docs_allowed_ips: str = ""

    @property
    def is_production(self) -> bool:
        """Returns True when running in the production environment."""
        return self.app_env.lower() == "production"

    @property
    def allowed_ips_set(self) -> set[str]:
        """Returns the parsed set of IPs allowed to view API docs in production."""
        if not self.docs_allowed_ips:
            return set()
        return {ip.strip() for ip in self.docs_allowed_ips.split(",") if ip.strip()}

    @field_validator("frontend_url", mode="before")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        """Remove any trailing slash from FRONTEND_URL to prevent double-slash URLs.
        
        Example: 'https://my-app.onrender.com/' → 'https://my-app.onrender.com'
        This ensures reset_url = f"{settings.frontend_url}/reset-password?token=..."
        always produces a valid single-slash URL.
        """
        return v.rstrip("/")
settings = Settings() #loaded from .env file