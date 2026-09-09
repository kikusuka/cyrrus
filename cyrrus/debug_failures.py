import sys, os, asyncio, shutil, traceback
sys.path.insert(0, r'c:\Users\DELL\Downloads\cyrrus\cyrrus')
os.chdir(r'c:\Users\DELL\Downloads\cyrrus\cyrrus')

DB = r'c:\Users\DELL\Downloads\cyrrus\cyrrus\_debug.db'
for ext in ['', '-wal', '-shm']:
    try: os.remove(DB + ext)
    except FileNotFoundError: pass

from cyrrus.memory import MemoryVault
from cyrrus.sqlite_backend import SQLiteBackend

LOG = r'c:\Users\DELL\Downloads\cyrrus\cyrrus\debug_failures.log'

async def main():
    with open(LOG, 'w', encoding='utf-8', buffering=1) as log_fh:
        def log(s):
            log_fh.write(str(s) + '\n')
            print(s, flush=True)

        # =============== FAILURE 1: 100 upserts same kw ===============
        log('\n' + '='*70)
        log('FAILURE 1 REPRO: 100 upserts of same keyword ("name")')
        log('='*70)
        vault = MemoryVault(db_path=DB)

        # Direct DB access to inspect actual rows
        backend = vault._backend
        conn = backend._conn

        for i in range(100):
            await vault.upsert("u", "name", f"version_{i}", 2)
            if i in (0, 1, 2, 99):
                cur = conn.execute("SELECT rowid, session_id, keyword, value, valid_at, invalid_at, version FROM facts ORDER BY rowid DESC LIMIT 5")
                rows = cur.fetchall()
                log(f'\nAfter upsert #{i} (version_{i}): last 5 rows:')
                for r in rows:
                    log(f'  rowid={r[0]} sess={r[1]} kw={r[2]} val={r[3][:20]:<20} valid={r[4][:19] if r[4] else None} invalid={r[5][:19] if r[5] else None} v={r[6]}')

        log('\n--- Count total rows ---')
        cur = conn.execute("SELECT COUNT(*) FROM facts WHERE session_id=? AND keyword=?", ("u", "name"))
        total_rows = cur.fetchone()[0]
        log(f'Total rows for (u, name): {total_rows}')

        log('\n--- Count CURRENT rows (invalid_at IS NULL) ---')
        cur = conn.execute("SELECT COUNT(*) FROM facts WHERE session_id=? AND keyword=? AND invalid_at IS NULL", ("u", "name"))
        curr_count = cur.fetchone()[0]
        log(f'Current rows for (u, name): {curr_count}')

        cur = conn.execute("SELECT rowid, value, valid_at, invalid_at FROM facts WHERE session_id=? AND keyword=? AND invalid_at IS NULL ORDER BY rowid", ("u", "name"))
        current_rows = cur.fetchall()
        log(f'Current rows list: {current_rows}')

        log('\n--- Calling retrieve("u", "name", limit=5) ---')
        try:
            results = await vault.retrieve("u", "name", limit=5)
            log(f'retrieve returned {len(results)} results:')
            for r in results:
                log(f'  {r.id}: {r.content}')
            if len(results) == 1 and "version_99" in results[0].content:
                log('EXPECTED: PASS (1 result, version_99)')
            else:
                log(f'EXPECTED: 1 result with version_99 — FAILURE!')
        except Exception as e:
            log(f'retrieve CRASHED: {type(e).__name__}: {e}')
            traceback.print_exc(file=log_fh)

        # =============== FAILURE 2: get_fact_history ===============
        log('\n\n' + '='*70)
        log('FAILURE 2 REPRO: 2 upserts -> get_fact_history')
        log('='*70)
        for ext in ['', '-wal', '-shm']:
            try: os.remove(DB + ext)
            except FileNotFoundError: pass

        memory = MemoryVault(db_path=DB)
        backend2 = memory._backend
        conn2 = backend2._conn

        await memory.upsert("test_session", "user_language", "Python", 1)
        log('\nAfter first upsert (Python):')
        cur = conn2.execute("SELECT rowid, keyword, value, valid_at, invalid_at, version FROM facts ORDER BY rowid")
        for r in cur.fetchall():
            log(f'  rowid={r[0]} kw={r[1]} val={r[2]} valid={r[3][:19] if r[3] else None} invalid={r[4][:19] if r[4] else None} v={r[5]}')

        await asyncio.sleep(0.1)
        await memory.upsert("test_session", "user_language", "JavaScript", 1)
        log('\nAfter second upsert (JavaScript):')
        cur = conn2.execute("SELECT rowid, keyword, value, valid_at, invalid_at, version FROM facts ORDER BY rowid")
        for r in cur.fetchall():
            log(f'  rowid={r[0]} kw={r[1]} val={r[2]} valid={r[3][:19] if r[3] else None} invalid={r[4][:19] if r[4] else None} v={r[5]}')

        log('\n--- Calling get_fact_history("test_session", "user_language") ---')
        try:
            history = await memory.get_fact_history("test_session", "user_language")
            log(f'get_fact_history returned {len(history)} entries:')
            for h in history:
                log(f'  value="{h["value"]}", invalid_at={h["invalid_at"] is not None}')
            if len(history) == 2:
                log('EXPECTED: PASS (2 entries)')
            else:
                log('EXPECTED: 2 entries — FAILURE!')
        except Exception as e:
            log(f'get_fact_history CRASHED: {type(e).__name__}: {e}')
            traceback.print_exc(file=log_fh)

asyncio.run(main())
for ext in ['', '-wal', '-shm']:
    try: os.remove(DB + ext)
    except FileNotFoundError: pass
