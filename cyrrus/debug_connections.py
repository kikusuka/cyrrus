import asyncio
import os
import time
import sqlite3

# Track connections using a wrapper class
class TrackedConnection:
    def __init__(self, conn, path, tracker):
        self._conn = conn
        self._path = path
        self._tracker = tracker
        self._closed = False
    
    def __getattr__(self, name):
        return getattr(self._conn, name)
    
    def close(self):
        if not self._closed:
            self._closed = True
            self._tracker.on_close(self)
            self._conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
        return False

class ConnectionTracker:
    def __init__(self):
        self.connections = []
        self._original_connect = sqlite3.connect
    
    def connect(self, *args, **kwargs):
        conn = self._original_connect(*args, **kwargs)
        tracked = TrackedConnection(conn, args[0] if args else 'unknown', self)
        self.connections.append(tracked)
        print('  OPEN connection to {} (total open: {})'.format(args[0] if args else 'unknown', len([c for c in self.connections if not c._closed])))
        return tracked
    
    def on_close(self, tracked_conn):
        print('  CLOSE connection to {} (total open: {})'.format(tracked_conn._path, len([c for c in self.connections if not c._closed]) - 1))
    
    def close_all(self):
        for c in self.connections:
            if not c._closed:
                try:
                    c.close()
                except:
                    pass
        self.connections.clear()

tracker = ConnectionTracker()
sqlite3.connect = tracker.connect

from cyrrus.memory import MemoryVault

DB = 'temporal_memory_test.db'

def cleanup():
    print('Cleanup called')
    for ext in ['', '-wal', '-shm']:
        for attempt in range(3):
            try:
                os.remove(DB + ext)
                print('  Removed:', DB + ext)
                break
            except FileNotFoundError:
                print('  Not found:', DB + ext)
                break
            except PermissionError as e:
                print('  PermissionError:', DB + ext, e)
                if attempt < 2:
                    time.sleep(0.1)
                else:
                    print('  Gave up on:', DB + ext)

async def count_rows(session_id):
    conn = tracker.connect(DB)
    try:
        return conn.execute('SELECT COUNT(*) FROM facts WHERE session_id=?', (session_id,)).fetchone()[0]
    finally:
        conn.close()

async def test_no_deletion_on_update():
    print('=== test_no_deletion_on_update ===')
    cleanup()
    
    memory = MemoryVault(db_path=DB)
    
    session_id = 'test_session'
    
    # Insert initial fact
    await memory.upsert(session_id, 'fact1', 'value1', 1)
    count1 = await count_rows(session_id)
    print('After 1 insert:', count1, 'rows')
    
    print('Active connections before cleanup:', len([c for c in tracker.connections if not c._closed]))
    cleanup()

asyncio.run(test_no_deletion_on_update())
print('Active connections at end:', len([c for c in tracker.connections if not c._closed]))
tracker.close_all()