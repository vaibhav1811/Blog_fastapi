# FastAPI Blog Application

A modern, asynchronous blogging platform built with **FastAPI**, featuring user authentication, post management, profile pictures, and password reset functionality. This application demonstrates best practices in async Python web development with SQLAlchemy ORM, JWT authentication, and cloud storage integration.

## 📋 Table of Contents

- [Project Overview](#project-overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Environment Configuration](#environment-configuration)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [Database Migrations](#database-migrations)
- [Development](#development)
- [Project Architecture](#project-architecture)
- [Contributing](#contributing)

## 📝 Project Overview

The FastAPI Blog is a full-featured blogging platform that enables users to create accounts, write blog posts, interact with others' posts, and manage their profiles. Built with modern Python async/await patterns, the application emphasizes performance, security, and scalability.

### Key Highlights:
- **Asynchronous Operations**: All database operations are fully async using SQLAlchemy's async engine
- **Secure Authentication**: JWT-based authentication with Argon2 password hashing
- **Cloud Storage**: AWS S3 integration for scalable image storage
- **Database Migrations**: Alembic for version-controlled schema management
- **RESTful API**: Clean, well-structured API endpoints with proper HTTP status codes
- **Email Support**: Password reset emails with secure token-based links
- **Responsive Frontend**: Jinja2 templates with modern CSS and JavaScript

## ✨ Features

### User Management
- **User Registration**: Create new user accounts with email validation
- **User Authentication**: Secure login with JWT tokens
- **Profile Management**: Update user information and profile pictures
- **Profile Picture Upload**: Upload and automatic image processing (resize, optimize)
- **Password Reset**: Secure password reset flow via email with time-limited tokens
- **User Profiles**: View user information and their published posts

### Blog Posts
- **Create Posts**: Write and publish blog posts with title and content
- **Read Posts**: Browse all posts with pagination support
- **Update Posts**: Edit existing posts
- **Delete Posts**: Remove posts (with proper authorization)
- **Post Likes**: Like/unlike posts with like counter
- **Pagination**: Efficient paginated post listing

### Security Features
- **JWT Authentication**: Stateless authentication with access tokens
- **Password Hashing**: Argon2 algorithm for secure password storage
- **Token Hash Storage**: Password reset tokens stored as SHA-256 hashes
- **CORS Support**: Configurable cross-origin requests
- **Input Validation**: Pydantic models for request/response validation

## 🛠 Tech Stack

### Backend Framework
- **FastAPI 0.136.1+**: Modern, fast web framework with automatic API documentation
  - Built-in data validation with Pydantic
  - Automatic OpenAPI/Swagger documentation
  - Native async/await support
  - Dependency injection system

### Database
- **SQLAlchemy 2.0.50+**: Async-first ORM for database operations
  - `AsyncSession` for non-blocking database calls
  - Declarative mapping with `Mapped` type hints
  - Relationship management and cascading deletes
  - Query optimization with `selectinload`
- **SQLite + Async Driver**: Development database with async support
  - `aiosqlite 0.22.1+`: Async SQLite driver
  - `greenlet 3.5.1+`: Context switching for async operations
- **Alembic 1.18.4+**: Database migration framework
  - Version control for schema changes
  - Automated migration generation

### Authentication & Security
- **PyJWT 2.13.0+**: JSON Web Token creation and verification
  - HS256 (HMAC-SHA256) signing algorithm
  - Configurable token expiration
- **pwdlib[argon2] 0.3.0+**: Password hashing library
  - Argon2 algorithm for robust password hashing
  - Built-in verification methods
- **OAuth2PasswordBearer**: FastAPI security scheme implementation

### Image Processing
- **Pillow 11.0.0+**: PIL/Pillow library for image manipulation
  - Profile picture upload and processing
  - Image resizing and optimization
  - Format validation (JPEG, PNG, GIF)

### Configuration & Environment
- **Pydantic Settings 2.14.0+**: Environment-based configuration
  - `.env` file support
  - Type-safe settings with Pydantic validation
  - SecretStr for sensitive configuration values

### Cloud Storage
- **Boto3 1.43.29+**: AWS SDK for Python
  - AWS S3 integration for image storage
  - Bucket management
  - Error handling for S3 operations

### Email Support
- **aiosmtplib 5.1.1+**: Async SMTP client
  - Non-blocking email sending
  - Password reset email notifications

### Additional Dependencies
- **asyncpg 0.31.0+**: PostgreSQL async driver (for production)
- **psycopg[binary] 3.3.4+**: PostgreSQL support
- **Starlette exceptions**: Enhanced exception handling

## 📁 Project Structure

```
fastapi_blog/
├── alembic/                          # Database migrations
│   ├── env.py                        # Migration environment configuration
│   ├── script.py.mako               # Migration template
│   └── versions/                     # Migration files
│       ├── 70f4b9bce847_add_likes_to_posts.py
│       └── e99961aeadfa_initial_scheme.py
├── routers/                          # API route handlers
│   ├── __init__.py
│   ├── users.py                      # User endpoints (auth, profile, etc.)
│   └── posts.py                      # Post endpoints (CRUD operations)
├── templates/                        # Jinja2 HTML templates
│   ├── layout.html                   # Base template
│   ├── home.html                     # Home page
│   ├── login.html                    # Login page
│   ├── register.html                 # Registration page
│   ├── account.html                  # User account page
│   ├── user_posts.html               # User posts listing
│   ├── post.html                     # Single post view
│   ├── forgot_password.html          # Password reset request
│   ├── reset_password.html           # Password reset form
│   ├── error.html                    # Error page
│   └── email/
│       └── password_reset.html       # Password reset email template
├── static/                           # Static files
│   ├── css/
│   │   └── main.css                  # Stylesheet
│   ├── js/
│   │   ├── auth.js                   # Authentication logic
│   │   └── utils.js                  # Utility functions
│   └── profile_pics/                 # Profile picture storage
├── media/                            # Media directory
│   └── profile_pics/                 # Uploaded profile pictures
├── populate_images/                  # Sample images for seeding
│   └── bg1.avif                      # Sample image
├── main.py                           # FastAPI application entry point
├── models.py                         # SQLAlchemy ORM models
├── schemas.py                        # Pydantic request/response schemas
├── auth.py                           # Authentication utilities & JWT handling
├── database.py                       # Database configuration & session management
├── config.py                         # Application configuration settings
├── email_utils.py                    # Email sending utilities
├── image_utils.py                    # Image processing utilities
├── populate_db.py                    # Database seeding script
├── check_s3.py                       # AWS S3 connectivity check
├── alembic.ini                       # Alembic configuration
├── pyproject.toml                    # Project metadata & dependencies
├── requirements.txt                  # Python dependencies
├── .env                              # Environment variables (not in repo)
└── README.md                         # This file
```

## 📦 Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.13+**: The application requires Python 3.13 or higher
- **UV Package Manager** (recommended): Fast, reliable Python package manager
  - Install from: https://astral.sh/uv
  - Or use `pip` as an alternative
- **Git**: For version control and cloning the repository
- **AWS Account** (optional): For production image storage via S3
  - AWS Access Key ID
  - AWS Secret Access Key
  - S3 bucket created in your preferred region

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/vaibhav1811/Blog_fastapi.git
cd fastapi_blog
```

### 2. Create a Virtual Environment

Using **UV** (recommended):
```bash
uv venv
```

Using **Python venv**:
```bash
python -m venv venv
```

### 3. Activate the Virtual Environment

**On Windows (PowerShell)**:
```powershell
.\.venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt)**:
```cmd
.\.venv\Scripts\activate.bat
```

**On macOS/Linux**:
```bash
source venv/bin/activate
```

### 4. Install Dependencies

Using **UV**:
```bash
uv sync
```

Using **Pip**:
```bash
pip install -r requirements.txt
```

## ⚙️ Environment Configuration

Create a `.env` file in the project root directory with the following configuration:

```env
# Database Configuration
# For SQLite (development): sqlite+aiosqlite:///./database.db
# For PostgreSQL: postgresql+asyncpg://user:password@localhost/db_name
DATABASE_URL=sqlite+aiosqlite:///./database.db

# JWT Configuration
SECRET_KEY=your-super-secret-key-change-this-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# S3 Configuration (for image storage)
S3_BUCKET_NAME=your-bucket-name
S3_REGION=eu-north-1
S3_ACCESS_KEY_ID=your-aws-access-key
S3_SECRET_ACCESS_KEY=your-aws-secret-key
S3_ENDPOINT_URL=                    # Optional: for custom S3-compatible services

# Image Upload Settings
MAX_UPLOAD_SIZE_BYTES=5242880       # 5 MB
ALLOWED_IMAGE_FORMATS=JPEG,PNG,GIF

# Pagination
POST_PER_PAGE=10

# Password Reset
RESET_TOKEN_EXPIRE_MINUTES=30

# Email Configuration (for password reset emails)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=your-email@gmail.com
SENDER_PASSWORD=your-app-password
```

### Configuration Details:

- **DATABASE_URL**: Connection string for your database
  - SQLite for development (fastest setup)
  - PostgreSQL for production (recommended)

- **SECRET_KEY**: Used for signing JWT tokens
  - Must be kept secret and long
  - Change this value in production
  - Generate a secure key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

- **S3 Configuration**: AWS S3 credentials for image storage
  - Create an IAM user with S3 permissions
  - Store credentials securely (use IAM roles in production)

- **Email Configuration**: SMTP settings for password reset emails
  - For Gmail, use app-specific passwords
  - Enable less secure apps or use OAuth2 in production

## ▶️ Running the Application

### 1. Apply Database Migrations

```bash
alembic upgrade head
```

### 2. Start the Development Server

Using **UV**:
```bash
uv run uvicorn main:app --reload
```

Using **Python**:
```bash
uvicorn main:app --reload
```

The application will be available at:
- **API**: http://localhost:8000
- **Interactive API Docs (Swagger UI)**: http://localhost:8000/docs
- **Alternative API Docs (ReDoc)**: http://localhost:8000/redoc

### 3. Verify AWS S3 Connection (Optional)

```bash
uv run check_s3.py
```

This validates that your AWS S3 credentials are correctly configured.

### 4. Populate Database with Sample Data (Optional)

```bash
uv run populate_db.py
```

This script seeds the database with sample users and posts for testing.

## 📚 API Endpoints

### User Endpoints (`/api/users`)

#### Register User
```http
POST /api/users
Content-Type: application/json

{
    "username": "john_doe",
    "email": "john@example.com",
    "password": "secure_password123"
}
```

**Response (201 Created)**:
```json
{
    "id": 1,
    "username": "john_doe",
    "email": "john@example.com",
    "image_file": null,
    "image_path": "/static/profile_pics/default.jpg"
}
```

#### Login
```http
POST /api/users/token
Content-Type: application/x-www-form-urlencoded

username=john_doe&password=secure_password123
```

**Response (200 OK)**:
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer"
}
```

#### Get Current User Profile
```http
GET /api/users/me
Authorization: Bearer <access_token>
```

#### Update User Profile
```http
PUT /api/users/me
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "username": "jane_doe",
    "email": "jane@example.com"
}
```

#### Upload Profile Picture
```http
PUT /api/users/me/upload-image
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file: <image_file>
```

#### Change Password
```http
POST /api/users/change-password
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "old_password": "current_password",
    "new_password": "new_secure_password"
}
```

#### Request Password Reset
```http
POST /api/users/forgot-password
Content-Type: application/json

{
    "email": "john@example.com"
}
```

#### Reset Password with Token
```http
POST /api/users/reset-password
Content-Type: application/json

{
    "token": "reset_token_from_email",
    "new_password": "new_secure_password"
}
```

#### Get User Posts
```http
GET /api/users/{user_id}/posts?skip=0&limit=10
```

### Post Endpoints (`/api/posts`)

#### Get All Posts (Paginated)
```http
GET /api/posts?skip=0&limit=10
```

**Response (200 OK)**:
```json
{
    "posts": [
        {
            "id": 1,
            "title": "My First Blog Post",
            "content": "This is the content of my first post...",
            "date_posted": "2025-04-22T10:30:00+00:00",
            "user_id": 1,
            "likes": 5,
            "author": {
                "id": 1,
                "username": "john_doe",
                "email": "john@example.com",
                "image_path": "https://s3.example.com/profile_pics/user1.jpg"
            }
        }
    ],
    "total": 42,
    "skip": 0,
    "limit": 10,
    "has_more": true
}
```

#### Create Post
```http
POST /api/posts
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "title": "My New Blog Post",
    "content": "This is the content of my new post..."
}
```

**Response (201 Created)**:
```json
{
    "id": 43,
    "title": "My New Blog Post",
    "content": "This is the content of my new post...",
    "date_posted": "2025-04-23T14:20:00+00:00",
    "user_id": 1,
    "likes": 0,
    "author": {
        "id": 1,
        "username": "john_doe",
        "email": "john@example.com",
        "image_path": "/static/profile_pics/default.jpg"
    }
}
```

#### Get Single Post
```http
GET /api/posts/{post_id}
```

#### Update Post
```http
PUT /api/posts/{post_id}
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "title": "Updated Title",
    "content": "Updated content..."
}
```

#### Delete Post
```http
DELETE /api/posts/{post_id}
Authorization: Bearer <access_token>
```

#### Like a Post
```http
POST /api/posts/{post_id}/like
Authorization: Bearer <access_token>
```

#### Unlike a Post
```http
DELETE /api/posts/{post_id}/like
Authorization: Bearer <access_token>
```

## 🗄️ Database Migrations

This project uses **Alembic** for database version control and migrations.

### Migration Commands

#### View Current Migration Status
```bash
alembic current
```

#### View Migration History
```bash
alembic history
```

#### Apply All Pending Migrations
```bash
alembic upgrade head
```

#### Create a New Migration
```bash
alembic revision --autogenerate -m "Description of changes"
```

Example:
```bash
alembic revision --autogenerate -m "Add user bio field"
```

#### Downgrade to Previous Version
```bash
alembic downgrade -1
```

#### Downgrade to Specific Version
```bash
alembic downgrade <revision_id>
```

### Database Schema Overview

#### Users Table
```sql
users (
    id: INTEGER PRIMARY KEY,
    username: STRING UNIQUE NOT NULL,
    email: STRING UNIQUE NOT NULL,
    password_hash: STRING NOT NULL,
    image_file: STRING NULLABLE,
    created_at: DATETIME NULLABLE
)
```

#### Posts Table
```sql
posts (
    id: INTEGER PRIMARY KEY,
    title: STRING NOT NULL,
    content: TEXT NOT NULL,
    user_id: INTEGER FOREIGN KEY,
    date_posted: DATETIME NOT NULL,
    likes: INTEGER DEFAULT 0
)
```

#### Password Reset Tokens Table
```sql
password_reset_tokens (
    id: INTEGER PRIMARY KEY,
    user_id: INTEGER FOREIGN KEY,
    token_hash: STRING UNIQUE NOT NULL,
    expires_at: DATETIME NOT NULL,
    created_at: DATETIME NOT NULL
)
```

## 🔧 Development

### Project Setup for Development

1. Install pre-commit hooks (optional):
```bash
pip install pre-commit
pre-commit install
```

2. Run tests (if tests are added):
```bash
pytest
```

3. Format code with black:
```bash
black .
```

4. Lint with flake8:
```bash
flake8 .
```

### Useful Development Commands

#### Access Interactive API Documentation
Visit http://localhost:8000/docs in your browser to explore and test all API endpoints interactively.

#### View Database Contents with Prisma Studio
```bash
prisma-studio         # If using Prisma
# OR
sqlite3 database.db   # Direct SQLite access
```

#### Check Database Schema
```bash
alembic current
alembic history
```

#### Generate Sample Data
```bash
uv run populate_db.py
```

#### Test S3 Connectivity
```bash
uv run check_s3.py
```

## 🏗️ Project Architecture

### Application Flow

```
Request → FastAPI Router
         ↓
    Dependency Injection (Authentication)
         ↓
    Route Handler (Validation with Pydantic)
         ↓
    Database Query (SQLAlchemy AsyncSession)
         ↓
    Response Model (Pydantic Serialization)
         ↓
    HTTP Response
```

### Key Design Patterns

1. **Async/Await Pattern**: All I/O operations (database, file uploads) are non-blocking
2. **Dependency Injection**: FastAPI `Depends()` for authentication and database sessions
3. **ORM with SQLAlchemy**: Type-safe database queries with automatic validation
4. **Pydantic Schemas**: Request/response validation and documentation
5. **Modular Routing**: Separate routers for users and posts for better organization
6. **Configuration Management**: Environment-based settings with Pydantic Settings

### Security Measures

1. **Password Hashing**: Argon2 algorithm for secure password storage
2. **JWT Authentication**: Stateless token-based authentication
3. **Token Expiration**: Configurable token expiration for enhanced security
4. **Secure Password Resets**: Time-limited, hashed tokens for password reset
5. **Input Validation**: Pydantic models validate all incoming data
6. **SQL Injection Prevention**: SQLAlchemy parameterized queries
7. **CORS Configuration**: Configurable cross-origin requests

### Performance Optimizations

1. **Async Database Operations**: All queries use async/await to prevent blocking
2. **Query Optimization**: `selectinload` to prevent N+1 query problems
3. **Pagination**: Efficient data loading with skip/limit parameters
4. **Image Optimization**: Pillow automatically optimizes uploaded images
5. **S3 Storage**: Cloud storage prevents server bloat
6. **Connection Pooling**: SQLAlchemy manages database connection pooling

## 📋 Database Models Overview

### User Model
- Stores user account information
- Relationship with posts (one-to-many)
- Relationship with password reset tokens
- Optional profile picture reference

### Post Model
- Contains blog post content
- Foreign key reference to author (User)
- Likes counter for engagement
- Timestamped with creation date

### PasswordResetToken Model
- Stores hashed reset tokens
- Linked to user account
- Includes expiration timestamp
- Automatically cleaned up when user is deleted

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Troubleshooting

### Common Issues

#### "ModuleNotFoundError: No module named 'fastapi'"
- Ensure virtual environment is activated
- Run `uv sync` or `pip install -r requirements.txt`

#### "Database URL is invalid"
- Check `.env` file for correct `DATABASE_URL`
- Ensure database file has write permissions

#### "JWT signature verification failed"
- Ensure `SECRET_KEY` in `.env` is set and consistent
- Check token hasn't expired

#### "AWS S3 connection failed"
- Verify AWS credentials in `.env`
- Check S3 bucket name and region
- Ensure IAM user has S3 permissions

#### "Email not sending"
- Verify SMTP credentials in `.env`
- For Gmail, use app-specific passwords
- Check firewall/network settings

### Getting Help

- Check the [FastAPI documentation](https://fastapi.tiangolo.com/)
- Review [SQLAlchemy async guide](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- Consult [Alembic documentation](https://alembic.sqlalchemy.org/)

## 📞 Contact & Support

For questions or support, please open an issue on the GitHub repository.

---

**Happy Blogging! 🎉**

Built with ❤️ using FastAPI
