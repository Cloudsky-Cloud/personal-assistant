import pytest
import pytest_asyncio
import tempfile
import os
from unittest.mock import patch


@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with patch("src.memory.database.settings") as mock_s:
            mock_s.db_path = db_path
            from src.memory.database import Database
            database = Database()
            await database.connect()
            yield database
            await database.close()


@pytest.mark.asyncio
async def test_upsert_and_get_user(db):
    await db.upsert_user(12345, "testuser", "Test")
    user = await db.get_user(12345)
    assert user is not None
    assert user["telegram_id"] == 12345
    assert user["username"] == "testuser"
    assert user["first_name"] == "Test"


@pytest.mark.asyncio
async def test_upsert_user_updates_on_conflict(db):
    await db.upsert_user(12345, "oldname", "Old")
    await db.upsert_user(12345, "newname", "New")
    user = await db.get_user(12345)
    assert user["username"] == "newname"


@pytest.mark.asyncio
async def test_save_and_get_messages(db):
    await db.upsert_user(12345, "u", "U")
    await db.save_message(12345, "user", "hello world")
    await db.save_message(12345, "assistant", "Hi there!")
    messages = await db.get_recent_messages(12345)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello world"
    assert messages[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_message_limit(db):
    await db.upsert_user(12345, "u", "U")
    for i in range(10):
        await db.save_message(12345, "user", f"message {i}")
    messages = await db.get_recent_messages(12345, limit=5)
    assert len(messages) == 5


@pytest.mark.asyncio
async def test_save_and_get_tasks(db):
    await db.upsert_user(12345, "u", "U")
    await db.save_task(
        12345, "Buy groceries", "Milk and bread", urgency=0.8, importance=0.6
    )
    tasks = await db.get_pending_tasks(12345)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Buy groceries"
    assert tasks[0]["priority_score"] == pytest.approx(0.7)


@pytest.mark.asyncio
async def test_task_status_update(db):
    await db.upsert_user(12345, "u", "U")
    await db.save_task(12345, "Test task", urgency=0.5, importance=0.5)
    tasks = await db.get_pending_tasks(12345)
    assert len(tasks) == 1
    await db.update_task_status(tasks[0]["id"], "completed")
    pending = await db.get_pending_tasks(12345)
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_preferences(db):
    await db.upsert_user(12345, "u", "U")
    await db.set_user_preference(12345, "briefing_style", "terse")
    prefs = await db.get_user_preferences(12345)
    assert prefs["briefing_style"] == "terse"


@pytest.mark.asyncio
async def test_get_all_user_ids(db):
    await db.upsert_user(111, "a", "A")
    await db.upsert_user(222, "b", "B")
    ids = await db.get_all_user_ids()
    assert set(ids) == {111, 222}
