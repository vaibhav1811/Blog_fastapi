import os
import sys
import asyncio
from collections.abc import AsyncGenerator # for async generator type hinting,use AsyncGenerator instead of Generator

# Fix for Windows: Psycopg doesn't support ProactorEventLoop, use SelectorEventLoop instead
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://bloguser:blogpassword@localhost/test_blog"
)
os.environ["S3_BUCKET_NAME"] = "test-bucket"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"

os.environ["S3_ACCESS_KEY_ID"] = "testing"
os.environ["S3_SECRET_ACCESS_KEY"] = "testing"
os.environ["S3_REGION"] = "us-east-1"

os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

import boto3
import pytest
from httpx import ASGITransport, AsyncClient # for async testing with httpx, use AsyncClient and ASGITransport 
from moto import mock_aws                    # for mocking AWS services in tests, use moto's mock_aws decorator 
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool         # for testing, use NullPool to avoid connection pooling issues     

from database import Base, get_db
from main import app

pytest_plugins=["anyio"]  # for async testing with pytest, use anyio plugin.

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


## Test Engine
@pytest.fixture(scope="session") # for creating a test database engine, use a session-scoped fixture to create an async engine with NullPool to avoid connection pooling issues during testing.,event loop is automatically handled by pytest-asyncio, so we don't need to manage it manually in the fixture.
def test_engine():
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        poolclass=NullPool,
    )
    return engine

## Setup Database
@pytest.fixture(scope="session")
async def setup_database(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all) # create tables before tests run,syncroniusly run the create_all method using run_sync to ensure it works with the async engine.

    yield # yield to allow tests to run after setup

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # drop tables after tests complete, syncroniusly run the drop_all method using run_sync to ensure it works with the async engine.

    await test_engine.dispose()


## DB Session (Transactional Rollback)
@pytest.fixture  # we havent specified a scope for this fixture, so it defaults to function scope, meaning a new session will be created for each test function that uses it. This allows for transactional rollback after each test, ensuring test isolation and preventing side effects between tests.
async def db_session(
    test_engine,
    setup_database,
) -> AsyncGenerator[AsyncSession]:
    conn = await test_engine.connect()
    trans = await conn.begin()

    test_async_session = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",  # instead of real commit, create a savepoint for each test, allowing us to rollback to this point after the test completes, ensuring that changes made during the test do not affect other tests.
    )

    async with test_async_session() as session: # create an async session using the test engine connection, this session will be used in tests to interact with the database. 
        try:
            yield session
        finally:
            await session.close() # close the session after the test completes, ensuring that resources are properly cleaned up and released.
            await trans.rollback() # rollback the transaction after the test completes, ensuring that any changes made during the test do not persist and affect other tests.
            await conn.close()  # close the connection to the test engine after the test completes, ensuring that resources are properly cleaned up and released.

## Mocked AWS
@pytest.fixture
def mocked_aws():  # for mocking AWS services in tests, use moto's mock_aws decorator to create a fixture that sets up a mocked S3 client and creates a test bucket before yielding the client to the test function. After the test completes, the mocked AWS services will be automatically cleaned up.
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=os.environ["S3_BUCKET_NAME"])
        yield s3

## Client Fixture
@pytest.fixture
async def client(
    db_session: AsyncSession,
    mocked_aws,
) -> AsyncGenerator[AsyncClient]:

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db   # override the get_db dependency in the FastAPI app to use the test database session, allowing tests to interact with the test database instead of the production database.,so fastapi dependency injection will use the test db session instead of the real one.

    async with AsyncClient(         # this is what allows us to test our FastAPI app without actually running a server, by using ASGITransport to send requests directly to the app in memory. This allows for faster and more isolated tests, as we don't have to worry about network latency or other external factors that could affect the test results.
        transport=ASGITransport(app=app),  # use ASGITransport to send requests directly to the FastAPI app in memory, allowing for faster and more isolated tests without the need for a running server.,so it is a transport mechanism that allows us to send requests directly to the FastAPI app in memory, bypassing the need for a running server and allowing for faster and more isolated tests.
        base_url="http://test",
    ) as ac:
        yield ac # yield the AsyncClient to the test function, allowing it to send requests to the FastAPI app in memory and receive responses without the need for a running server.

    app.dependency_overrides.clear() # clear the dependency overrides after the test completes, ensuring that the FastAPI app is restored to its original state and that subsequent tests are not affected by any changes made during the test.

    # async client  with asgii transport does not run the apps lifespan events, so we need to manually trigger the startup and shutdown events of the FastAPI app to ensure that any necessary setup or teardown logic is executed before and after the tests run. This is done by calling the app's lifespan context manager directly, which will trigger the startup and shutdown events as if the app were running in a real server environment.



    ## Auth Helpers
async def create_test_user(
    client: AsyncClient,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> dict:
    response = await client.post(
        "/api/users",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, f"Failed to create user: {response.text}"
    return response.json()


async def login_user(
    client: AsyncClient,
    email: str = "test@example.com",
    password: str = "testpassword123",
) -> str:
    response = await client.post(
        "/api/users/token",
        data={
            "username": email,
            "password": password,
        }, # we are not using json here because the token endpoint expects form data, so we need to send the email and password as form data instead of JSON in the request body.
    )
    assert response.status_code == 200, f"Failed to login: {response.text}"
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}