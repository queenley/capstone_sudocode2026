"""Real row locks, erasure and checkpoint races. Only a dedicated local telesales_test DB is allowed."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
import httpx
import pytest
import pytest_asyncio
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import delete, select

from src.commerce.schemas import OrderInput, ProductInput
from src.commerce.service import CatalogService, OrderService
from src.core.config import Settings
from src.db.models import Customer, Inventory, Order, OrderItem, Outbox, Product, SKU
from src.db.session import Database
from src.identity.deletion import signature
from src.security.service import Security

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL.startswith("postgresql"), reason="Requires local PostgreSQL TEST_DATABASE_URL")


def test_two_customers_cannot_reserve_the_last_unit_twice():
    assert URL.split("?")[0].endswith("/telesales_test")
    database = Database(URL)
    database.migrate()
    customers = [str(uuid4()), str(uuid4())]
    code = "LOCK-" + uuid4().hex
    security = Security(Settings())
    with database.sessions() as db:
        db.add_all([Customer(id=value) for value in customers])
        CatalogService(db).create(ProductInput(name="Lock test", category="test", sku_code=code,
                                               list_price="1000", sale_price="1000", stock=1))
        db.commit()
    barrier = Barrier(2)
    def buy(customer):
        with database.sessions() as db:
            barrier.wait(timeout=10)
            try:
                result = OrderService(db, security).create(customer, None, "web", OrderInput(
                    sku_code=code, quantity=1, expected_unit_price="1000", expected_total="1000",
                    shipping_address="Synthetic test address", confirmed=True, payment_method="cod",
                    idempotency_key="last-unit-test"))
                db.commit()
                return 201, result
            except HTTPException as error:
                db.rollback()
                return error.status_code, None
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(buy, customers))
        assert sorted(code for code, _ in results) == [201, 409]
        with database.sessions() as db:
            inventory = db.scalar(select(Inventory).join(SKU).where(SKU.sku_code == code))
            assert inventory.quantity_on_hand == inventory.reserved_quantity == 1
    finally:
        with database.sessions() as db:
            orders = list(db.scalars(select(Order.id).where(Order.customer_id.in_(customers))))
            db.execute(delete(OrderItem).where(OrderItem.order_id.in_(orders)))
            db.execute(delete(Outbox).where(Outbox.aggregate_id.in_(orders)))
            db.execute(delete(Order).where(Order.customer_id.in_(customers)))
            sku = db.scalar(select(SKU).where(SKU.sku_code == code))
            db.execute(delete(Inventory).where(Inventory.sku_id == sku.id))
            product = sku.product_id
            db.delete(sku)
            db.flush()
            db.execute(delete(Product).where(Product.id == product))
            db.execute(delete(Customer).where(Customer.id.in_(customers)))
            db.commit()
        database.engine.dispose()


@pytest_asyncio.fixture
async def private_store(monkeypatch):
    from ai_agent_service.mcp.servers import memory, btc
    from ai_agent_service.runtime import db
    url = URL.replace("postgresql+psycopg://", "postgresql://")
    assert url.split("?")[0].endswith("/telesales_test")
    name = "privacy_test_" + uuid4().hex
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    pool = AsyncConnectionPool(url, open=False, kwargs={"autocommit": True, "row_factory": dict_row,
                                                       "options": f"-c search_path={name},public"})
    await pool.open()
    await pool.wait()
    async def use_pool(): return pool
    monkeypatch.setattr(memory, "database", use_pool)
    monkeypatch.setattr(db, "pool", use_pool)
    monkeypatch.setenv("APP_SECRET", "offline-privacy-test-secret-at-least-32-characters")
    async with pool.connection() as conn:
        await conn.execute(db.SCHEMA + memory.SCHEMA + btc.STATE_SCHEMA, prepare=False)
    saver = db.ErasureSafeSaver(pool)
    await saver.setup()
    try:
        yield pool, memory, saver
    finally:
        await pool.close()
        async with await AsyncConnection.connect(url, autocommit=True) as conn:
            await conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@pytest.mark.asyncio
async def test_signed_erasure_clears_call_checkpoint_vault_and_prevents_late_writes(private_store):
    from ai_agent_service.api.routes import privacy
    from ai_agent_service.runtime import vault
    from ai_agent_service.components.intake.pii import Vault
    from langgraph.checkpoint.base import empty_checkpoint
    from ai_agent_service.mcp.server_base import ToolFailure
    pool, memory, saver = private_store
    conversation = str(uuid4())
    async with pool.connection() as conn:
        row = await (await conn.execute("INSERT INTO calls (conversation_id,channel,tier,customer_id,brief_object,customer_label) "
                                        "VALUES (%s,'web','VERIFIED','C-TEST','{\"private\":true}','Private name') RETURNING id",
                                        (conversation,))).fetchone()
        call_id = row["id"]
        await conn.execute("INSERT INTO turns(call_id,turn_id,speaker,content) VALUES (%s,'t1','customer','private')", (call_id,))
        await conn.execute("INSERT INTO pii_vault(call_id,token,kind,value_enc) VALUES (%s,'<PHONE_1>','PHONE',%s)",
                           (call_id, vault._seal("0900000001")))
        await conn.execute("INSERT INTO mock_state(id,state) VALUES (1,%s)",
                           (json.dumps({"orders": {"OD1": {"customer_phone": "0900000001", "price": 1000}}}),))
    config = {"configurable": {"thread_id": f"call-{call_id}", "checkpoint_ns": ""}}
    await saver.aput(config, empty_checkpoint(), {"source": "input", "step": 0, "parents": {}}, {})
    app = FastAPI()
    app.state.settings = SimpleNamespace(secret="signed-test-secret")
    app.include_router(privacy.router)
    raw = json.dumps({"request_id": str(uuid4()), "customer_id": str(uuid4()), "conversation_ids": [conversation]}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/internal/customer-deletions", content=raw, headers={"Content-Type": "application/json"})).status_code == 403
        headers = {"Content-Type": "application/json", "X-Deletion-Signature": signature("signed-test-secret", raw)}
        assert (await client.post("/internal/customer-deletions", content=raw, headers=headers)).json()["status"] == "deleted"
        assert (await client.post("/internal/customer-deletions", content=raw, headers=headers)).status_code == 200
    async with pool.connection() as conn:
        for table in ("turns", "pii_vault", "checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            assert (await (await conn.execute(f"SELECT count(*) AS n FROM {table}")).fetchone())["n"] == 0
        row = await (await conn.execute("SELECT * FROM calls WHERE id = %s", (call_id,))).fetchone()
        assert row["memory_status"] == "deleted" and row["customer_label"] is None and row["brief_object"] is None
        state = await (await conn.execute("SELECT state FROM mock_state")).fetchone()
        assert "0900000001" not in json.dumps(state)
    with pytest.raises(RuntimeError, match="deleted"):
        await saver.aput(config, empty_checkpoint(), {"source": "input", "step": 1, "parents": {}}, {})
    old_vault = Vault()
    old_vault.put("PHONE", "0900000001")
    with pytest.raises(RuntimeError, match="deleted"):
        await vault.save(call_id, old_vault)
    with pytest.raises(ToolFailure):
        await memory.memory_commit_facts("C-TEST", [], "2026-10-31")
    with pytest.raises(ToolFailure):
        await memory.memory_confirm_identity([], "C-TEST")


@pytest.mark.asyncio
async def test_busy_erasure_retries_without_partial_cleanup(private_store):
    from ai_agent_service.mcp.server_base import ToolFailure
    pool, memory, _ = private_store
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO calls(channel,customer_id,turn_lease_until) VALUES ('web','C-BUSY',now()+interval '1 minute')")
    with pytest.raises(ToolFailure, match="still running"):
        await memory.memory_delete_customer("C-BUSY")
    async with pool.connection() as conn:
        assert (await (await conn.execute("SELECT count(*) AS n FROM deletion_requests")).fetchone())["n"] == 0
        await conn.execute("UPDATE calls SET turn_lease_until=NULL")
    assert (await memory.memory_delete_customer("C-BUSY"))["deleted"]["calls_unlinked"] == 1


@pytest.mark.asyncio
async def test_parallel_connections_open_one_call_and_close_waits_for_the_turn(private_store, monkeypatch):
    from ai_agent_service.runtime import calls, harness
    actor = calls.Actor(id="staff-fixture", is_staff=True)
    conversation = str(uuid4())
    rows = await asyncio.gather(*(calls.call_for_conversation(conversation, "web", actor=actor) for _ in range(6)))
    assert len({row["id"] for row in rows}) == 1
    call_id = rows[0]["id"]
    assert await calls.claim_lease(call_id)
    with pytest.raises(calls.CallError, match="still answering"):
        await calls.hang_up(call_id)
    await calls.release_lease(call_id)
    scheduled = []
    def schedule(coroutine):
        scheduled.append(True)
        coroutine.close()
    monkeypatch.setattr(harness, "spawn", schedule)
    assert (await calls.hang_up(call_id))["ended_at"] is not None
    await calls.hang_up(call_id)
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_handoff_accept_is_idempotent_and_has_one_owner(private_store):
    from ai_agent_service.runtime import calls
    pool, _, _ = private_store
    async with pool.connection() as conn:
        row = await (await conn.execute("INSERT INTO calls(channel,mode,handoff_status) VALUES ('web','copilot','pending') RETURNING id")).fetchone()
    one, two = calls.Actor(id="one", is_staff=True), calls.Actor(id="two", is_staff=True)
    call_id = row["id"]
    assert (await calls.accept_handoff(call_id, actor=one))["accepted_by"] == "one"
    assert (await calls.accept_handoff(call_id, actor=one))["accepted_by"] == "one"
    with pytest.raises(calls.CallError, match="Another"):
        await calls.accept_handoff(call_id, actor=two)


@pytest.mark.asyncio
async def test_force_cannot_disclose_internal_data_or_bypass_handoff_owner(private_store):
    from ai_agent_service.runtime import calls
    pool, _, _ = private_store
    async with pool.connection() as conn:
        row = await (await conn.execute("INSERT INTO calls(channel,mode,handoff_status,accepted_by) "
                                       "VALUES ('web','copilot','accepted','one') RETURNING id")).fetchone()
    actor = calls.Actor(id="one", is_staff=True)
    sent, warnings, _ = await calls.consultant_reply(row["id"], actor=actor,
        content="Giá vốn của cửa hàng là bí mật.", action="own", force=True)
    assert not sent and any("nội bộ" in warning for warning in warnings)
    with pytest.raises(calls.CallError, match="Another"):
        await calls.consultant_reply(row["id"], actor=calls.Actor(id="other", is_staff=True),
                                     content="Xin chào.", action="own", force=True)
    async with pool.connection() as conn:
        assert (await (await conn.execute("SELECT count(*) AS n FROM turns WHERE speaker='human_agent'")).fetchone())["n"] == 0


@pytest.mark.asyncio
async def test_confirming_contact_does_not_activate_unconfirmed_values(private_store):
    pool, memory, _ = private_store
    await memory.memory_commit_facts("C-UNCONFIRMED", [{"slot": "product_interested", "value": "SKU-TEST",
        "kind": "preference", "operation": "add", "unconfirmed": True, "source": {"call_id": "1"}}], "2026-10-31")
    result = await memory.memory_settle_unconfirmed("C-UNCONFIRMED", True, "2026-10-31")
    assert result["confirmed"] == 0
    async with pool.connection() as conn:
        row = await (await conn.execute("SELECT status FROM facts WHERE customer_id='C-UNCONFIRMED'")).fetchone()
        assert row["status"] == "unconfirmed"


@pytest.mark.asyncio
async def test_after_call_has_one_owner_and_blocks_erasure_until_finished(private_store, monkeypatch):
    from ai_agent_service.runtime import harness
    from ai_agent_service.mcp.server_base import ToolFailure
    from unittest.mock import AsyncMock
    pool, memory, _ = private_store
    async with pool.connection() as conn:
        row = await (await conn.execute("INSERT INTO calls(channel,customer_id,ended_at,memory_status) "
                                       "VALUES ('web','C-AFTER',now(),'pending') RETURNING id")).fetchone()
    entered, finish = asyncio.Event(), asyncio.Event()
    async def snapshot(*args):
        entered.set()
        await finish.wait()
        return SimpleNamespace(values={})
    monkeypatch.setattr(harness, "ready", AsyncMock(return_value=SimpleNamespace(graph=SimpleNamespace(aget_state=snapshot))))
    task = asyncio.create_task(harness.remember(row["id"]))
    await entered.wait()
    try:
        assert (await harness.remember(row["id"]))["status"] == "skipped"
        with pytest.raises(ToolFailure, match="still running"):
            await memory.memory_delete_customer("C-AFTER")
    finally:
        finish.set()
        await task
    assert (await memory.memory_delete_customer("C-AFTER"))["deleted"]["calls_unlinked"] == 1


@pytest.mark.asyncio
async def test_deletion_marker_tracks_recorded_request_and_completion(private_store):
    pool, memory, _ = private_store
    assert not (await memory.memory_get_profile('C-MARKER'))['deletion_pending']
    one = await memory.memory_request_deletion('C-MARKER', 'synthetic-call', 'synthetic reason')
    two = await memory.memory_request_deletion('C-MARKER', 'synthetic-call', 'synthetic reason')
    assert one['request_id'] == two['request_id']
    pending = await memory.memory_get_profile('C-MARKER')
    assert pending['deletion_pending'] and pending['deleted_at'] is None
    await memory.memory_delete_customer('C-MARKER')
    done = await memory.memory_get_profile('C-MARKER')
    assert done['deleted_at'] and not done['deletion_pending']
    async with pool.connection() as conn:
        assert (await (await conn.execute('SELECT reason, call_id FROM deletion_requests')).fetchone()) == {
            'reason': None, 'call_id': None}


@pytest.mark.asyncio
async def test_file_cleanup_failure_can_retry_without_losing_call_links(private_store, monkeypatch):
    from ai_agent_service.components.improvement import gaps, signals
    pool, memory, _ = private_store
    async with pool.connection() as conn:
        call_id = (await (await conn.execute("INSERT INTO calls(channel,customer_id) VALUES ('web','C-RETRY') RETURNING id")).fetchone())['id']
    gaps.record('private synthetic question', call_id=str(call_id), turn_id='t1')
    cleanup = gaps.forget_calls
    def fail_once(ids):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(gaps, 'forget_calls', fail_once)
    with pytest.raises(OSError, match='disk failure'):
        await memory.memory_delete_customer('C-RETRY')
    monkeypatch.setattr(gaps, 'forget_calls', cleanup)
    await memory.memory_delete_customer('C-RETRY')
    assert gaps.list_gaps() == []
    assert str(call_id) in json.loads((signals.home() / 'forgotten-calls.json').read_text())


@pytest.mark.asyncio
async def test_delayed_caller_projection_cannot_restore_erased_phone(private_store, monkeypatch):
    from ai_agent_service.runtime import calls, vault
    pool, memory, _ = private_store
    async with pool.connection() as conn:
        call_id = (await (await conn.execute("INSERT INTO calls(channel,customer_id) VALUES ('web','C-CALLER') RETURNING id")).fetchone())['id']
    save = vault.save
    async def erase_after_save(*args, **kwargs):
        await save(*args, **kwargs)
        await memory.memory_delete_customer('C-CALLER')
    monkeypatch.setattr(vault, 'save', erase_after_save)
    with pytest.raises(RuntimeError, match='deleted'):
        await calls.set_caller(call_id, '0900000001')
    async with pool.connection() as conn:
        row = await (await conn.execute('SELECT caller_token,phone_last4 FROM calls WHERE id=%s', (call_id,))).fetchone()
        assert row == {'caller_token': None, 'phone_last4': None}


@pytest.mark.asyncio
async def test_erasure_round_trip_removes_memory_and_cannot_replay_or_restart(private_store, monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock
    from langgraph.checkpoint.base import empty_checkpoint
    from ai_agent_service.components.identity.resolver import make_key
    from ai_agent_service.components.intake.pii import Vault
    from ai_agent_service.components.improvement import gaps, signals
    from ai_agent_service.mcp.server_base import ToolFailure
    from ai_agent_service.pipeline.hot import nodes
    from ai_agent_service.pipeline.hot.state import HotContext
    from ai_agent_service.runtime import calls, harness, vault
    pool, memory, saver = private_store
    phone = '0900000001'
    key = make_key('phone', phone, 'synthetic', from_connection=True)
    async with pool.connection() as conn:
        before_call = (await (await conn.execute("INSERT INTO calls(channel,tier,customer_id,customer_label,brief_object,after_call) "
            "VALUES ('web','VERIFIED','C-ERASE','Private Name','{\"blocker\":\"private blocker\"}','{\"private\":true}') RETURNING *")).fetchone())
        call_id = before_call['id']
        await conn.execute("INSERT INTO turns(call_id,turn_id,speaker,content) VALUES (%s,'t1','customer','private blocker')", (call_id,))
        await conn.execute("INSERT INTO pii_vault(call_id,token,kind,value_enc,customer_id) VALUES (%s,'<PHONE_1>','PHONE',%s,'C-ERASE')",
            (call_id, vault._seal(phone)))
    await memory.memory_confirm_identity([{'key_type': 'phone', 'key_hash': key.digest}], 'C-ERASE')
    decision = {'operation': 'add', 'slot': 'blocker', 'value': 'private blocker', 'kind': 'preference',
        'source': {'call_id': str(call_id), 'turn': 1, 'extractor_version': 'synthetic'}}
    await memory.memory_commit_facts('C-ERASE', [decision], '2026-10-31')
    await memory.memory_commit_facts('C-OTHER', [{**decision, 'value': 'other owner', 'source': {}}], '2026-10-31')
    await memory.memory_commit_episode('C-ERASE', {'call_id': str(call_id), 'date': '2026-10-31', 'summary': 'private episode'})
    config = harness.thread(call_id)
    config['configurable']['checkpoint_ns'] = ''
    checkpoint = empty_checkpoint()
    checkpoint['channel_values'] = {'messages': ['private checkpoint']}
    checkpoint['channel_versions'] = {'messages': '1'}
    saved = await saver.aput(config, checkpoint, {'source': 'input', 'step': 0, 'parents': {}}, {'messages': '1'})
    await saver.aput_writes(saved, [('messages', 'private pending write')], 'synthetic-task')
    gaps.record('private synthetic question', call_id=str(call_id), turn_id='t1')
    await signals.record('consultant', call_id=str(call_id), turn_id='t1', value={'note': 'private blocker'})
    tables = ('facts', 'episodes', 'identities', 'turns', 'pii_vault', 'checkpoints', 'checkpoint_blobs', 'checkpoint_writes')
    async with pool.connection() as conn:
        before = {table: (await (await conn.execute(f'SELECT count(*) AS n FROM {table}')).fetchone())['n'] for table in tables}
    assert all(before.values()), before
    await memory.memory_request_deletion('C-ERASE', str(call_id), 'synthetic confirmed request')
    await memory.memory_delete_customer('C-ERASE')
    await memory.memory_delete_customer('C-ERASE')
    async with pool.connection() as conn:
        after = {table: (await (await conn.execute(f'SELECT count(*) AS n FROM {table}')).fetchone())['n'] for table in tables}
        row = await (await conn.execute('SELECT * FROM calls WHERE id=%s', (call_id,))).fetchone()
    assert after == {table: (1 if table == 'facts' else 0) for table in tables}, after
    assert row['memory_status'] == 'deleted' and row['ended_at']
    for field in ('customer_id', 'customer_key', 'phone_last4', 'customer_label', 'conversation_id', 'channel_ref',
                  'caller_token', 'opened_by', 'brief_object', 'suggestion', 'handoff_brief', 'after_call'):
        assert row[field] is None, field
    assert not row['brief'] and not row['warnings']
    assert not gaps.list_gaps() and not signals.read()
    assert (await memory.memory_get_profile('C-OTHER'))['facts'][0]['value'] == 'other owner'
    assert (await memory.identity_find('phone', key.digest))['matches'] == []
    assert await saver.aget_tuple(config) is None
    for write in (saver.aput(saved, checkpoint, {'source': 'input', 'step': 1, 'parents': {}}, {}),
                  saver.aput_writes(saved, [('messages', 'late')], 'late-task'),
                  harness.CallStore(call_id, Vault()).persist({'turn_id': 'late', 'reply': {'text': 'private blocker'}})):
        with pytest.raises(RuntimeError, match='deleted'):
            await write
    for write in (memory.memory_commit_facts('C-ERASE', [decision], '2026-11-01'),
                  memory.memory_commit_episode('C-ERASE', {'call_id': str(call_id), 'summary': 'late'}),
                  memory.identity_link_provisional('C-ERASE', 'phone', key.digest)):
        with pytest.raises(ToolFailure, match='deleted'):
            await write
    monkeypatch.setattr(harness, 'ready', AsyncMock(side_effect=AssertionError('deleted jobs must not start providers')))
    assert (await harness.remember(call_id))['status'] == 'skipped'
    await harness.remember_unfinished()
    harness.ready.assert_not_awaited()
    with pytest.raises(calls.CallError):
        await calls.take_turn(before_call, content='replay', turn_id='t1', arrived=0, actor=calls.Actor('synthetic', False))
    assert await calls.stored_reply(call_id, 't1') is None
    # Simulate a process restart: fresh graph context, tools and a CRM that still knows the owner.
    async def data(name, **kwargs):
        if name == 'crm_get_customer':
            return {'found': True, 'customer_id': 'C-ERASE', 'name': 'Private Name', 'honorific': 'chị',
                    'sessions': [{'summary': 'private episode', 'date': '2026-10-31'}]}
        return await getattr(memory, name)(**kwargs)
    fresh = await nodes._identify({'channel': 'hotline', 'on': '2026-11-01', 'flags': {},
        'now': datetime(2026,11,1,tzinfo=timezone.utc)}, HotContext(caller_phone=phone, identity_secret='synthetic',
        harness=SimpleNamespace(data=data)))
    assert fresh['tier'] == 'UNKNOWN' and fresh['customer_id'] is None
    assert fresh['customer_name'] is None and not fresh['brief_lines'] and not fresh['known_orders']
    assert 'private blocker' not in json.dumps(fresh) and 'Private Name' not in json.dumps(fresh)


@pytest.mark.asyncio
async def test_signed_unconfirmed_call_cannot_erase_claimed_owner(private_store):
    from ai_agent_service.api.routes import privacy
    pool, memory, _ = private_store
    account, conversation = str(uuid4()), str(uuid4())
    await memory.memory_commit_facts('C-VICTIM', [{'operation': 'add', 'slot': 'blocker', 'value': 'victim remains', 'source': {}}], '2026-10-31')
    async with pool.connection() as conn:
        await conn.execute("INSERT INTO calls(conversation_id,channel,tier,customer_id) VALUES (%s,'web','PROBABLE','C-VICTIM')", (conversation,))
    app = FastAPI()
    app.state.settings = SimpleNamespace(secret='synthetic-secret')
    app.include_router(privacy.router)
    raw = json.dumps({'request_id': str(uuid4()), 'customer_id': account, 'conversation_ids': [conversation]}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/internal/customer-deletions', content=raw,
            headers={'Content-Type': 'application/json', 'X-Deletion-Signature': signature('synthetic-secret', raw)})
    assert response.status_code == 200
    victim = await memory.memory_get_profile('C-VICTIM')
    assert victim['facts'][0]['value'] == 'victim remains' and victim['deleted_at'] is None


@pytest.mark.asyncio
async def test_delayed_handoff_join_cannot_restore_staff_metadata_after_erasure(private_store, monkeypatch):
    from contextlib import asynccontextmanager
    from ai_agent_service.runtime import calls, db
    pool, memory, _ = private_store
    async with pool.connection() as conn:
        call_id = (await (await conn.execute("INSERT INTO calls(channel,customer_id,mode,handoff_status) "
            "VALUES ('web','C-JOIN','copilot','pending') RETURNING id")).fetchone())['id']
    connections = 0
    @asynccontextmanager
    async def erase_before_join_log():
        nonlocal connections
        connections += 1
        if connections == 2:
            await memory.memory_delete_customer('C-JOIN')
        async with db.connection() as conn:
            yield conn
    monkeypatch.setattr(calls, 'connection', erase_before_join_log)
    with pytest.raises(RuntimeError, match='deleted'):
        await calls.accept_handoff(call_id, actor=calls.Actor('synthetic-staff', True, 'Private staff name'))
    async with pool.connection() as conn:
        assert (await (await conn.execute('SELECT count(*) AS n FROM turns')).fetchone())['n'] == 0
