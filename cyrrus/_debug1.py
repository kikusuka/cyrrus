import sys
sys.path.insert(0, r'c:\Users\DELL\Downloads\cyrrus\cyrrus')
import os
os.chdir(r'c:\Users\DELL\Downloads\cyrrus\cyrrus')

DB = r'_debug.db'
for ext in ['', '-wal', '-shm']:
    try: os.remove(DB + ext)
    except FileNotFoundError: pass

import asyncio
from cyrrus.memory import MemoryVault

async def test_100_overwrites():
    # Direct stderr print - no buffering
    sys.stderr.write('\n=== FAILURE 1 REPRO: 100 upserts of same keyword ===\n')
    sys.stderr.flush()

    vault = MemoryVault(db_path=DB)
    backend = vault._backend
    conn = backend._conn

    for i in range(100):
        await vault.upsert("u", "name", f"version_{i}", 2)
        if i in (0, 1, 2, 98, 99):
            cur = conn.execute("SELECT COUNT(*) FROM facts WHERE session_id=? AND keyword=?", ("u", "name"))
            t = cur.fetchone()[0]
            cur2 = conn.execute("SELECT COUNT(*) FROM facts WHERE session_id=? AND keyword=? AND invalid_at IS NULL", ("u", "name"))
            c = cur2.fetchone()[0]
            sys.stderr.write(f'  After upsert #{i}: total={t}, current={c}\n')
            sys.stderr.flush()

    # Dump all current rows for (u, name)
    sys.stderr.write('\nAll CURRENT rows:\n')
    cur = conn.execute("SELECT rowid, value, valid_at, invalid_at, version FROM facts WHERE session_id=? AND keyword=? AND invalid_at IS NULL ORDER BY rowid", ("u", "name"))
    rows = cur.fetchall()
    for r in rows:
        sys.stderr.write(f'  {r}\n')
    sys.stderr.flush()

    results = await vault.retrieve("u", "name", limit=5)
    sys.stderr.write(f'\nretrieve() returned {len(results)} results:\n')
    for r in results:
        sys.stderr.write(f'  {r.id}: {r.content}\n')
    sys.stderr.write(f'Expected: 1 result with version_99\n')
    sys.stderr.write(f'RESULT: {"PASS" if len(results) == 1 and "version_99" in results[0].content else "FAIL"}\n')
    sys.stderr.flush()


asyncio.run(test_100_overwrites())

for ext in ['', '-wal', '-shm']:
    try: os.remove(DB + ext)
    except FileNotFoundError: pass
