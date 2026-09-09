import sys
import os
import io
import contextlib

WORK_DIR = r'c:\Users\DELL\Downloads\cyrrus\cyrrus'
sys.path.insert(0, WORK_DIR)
os.chdir(WORK_DIR)

LOG = r'c:\Users\DELL\Downloads\cyrrus\pytest_final.log'

def run_pytest_capture(args):
    """Run pytest with stdout/stderr captured to string."""
    import pytest
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with contextlib.redirect_stderr(buf):
            try:
                exitcode = pytest.main(args)
            except SystemExit as e:
                exitcode = e.code if e.code is not None else 0
    output = buf.getvalue()
    return exitcode, output

all_output = []
all_exit = 0

# ============ Part A: test_stemmer.py ============
ec, out = run_pytest_capture(['tests/test_stemmer.py', '-v', '--tb=short', '-p', 'no:warnings', '-q'])
all_output.append('\n===== test_stemmer.py (PART A) =====')
all_output.append(out[-2000:])
all_output.append(f'Exit: {ec}')
all_exit |= ec

# ============ Part B: test_backend.py ============
ec, out = run_pytest_capture(['tests/test_backend.py', '-v', '--tb=short', '-p', 'no:warnings', '-q'])
all_output.append('\n===== test_backend.py (PART B) =====')
all_output.append(out[-2000:])
all_output.append(f'Exit: {ec}')
all_exit |= ec

# ============ Part C: test_bm25.py ============
ec, out = run_pytest_capture(['tests/test_bm25.py', '-v', '--tb=short', '-p', 'no:warnings', '-q'])
all_output.append('\n===== test_bm25.py (PART C) =====')
all_output.append(out[-2000:])
all_output.append(f'Exit: {ec}')
all_exit |= ec

# ============ Existing test suite: test_v1.py ============
ec, out = run_pytest_capture(['tests/test_v1.py', '-v', '--tb=short', '-p', 'no:warnings', '-q'])
all_output.append('\n===== test_v1.py (EXISTING) =====')
all_output.append(out[-2000:])
all_output.append(f'Exit: {ec}')
all_exit |= ec

# ============ Existing: temporal, edge_cases, adversarial, etc ============
for existing in ['test_temporal_memory.py', 'test_edge_cases_simple.py',
                 'test_adversarial.py', 'test_session_locks.py',
                 'test_failsafe.py', 'test_compression.py',
                 'test_config_validation.py', 'test_threshold_calibration.py',
                 'test_token_consistency.py', 'test_streaming.py',
                 'test_cli.py', 'test_embedding_router.py',
                 'test_fact_extractor_tiers.py']:
    fpath = os.path.join('tests', existing)
    if not os.path.exists(fpath):
        all_output.append(f'\nSKIP (missing): {existing}')
        continue
    ec, out = run_pytest_capture([fpath, '-v', '--tb=line', '-p', 'no:warnings', '-q'])
    all_output.append(f'\n===== {existing} =====')
    # Just the summary line
    summary = [l for l in out.split('\n') if ('passed' in l.lower() or 'failed' in l.lower() or 'error' in l.lower()) and l.strip()]
    if summary:
        all_output.append('  ' + summary[-1])
    else:
        all_output.append('  (no summary line, last 200 chars:)')
        all_output.append('  ' + out[-200:].replace('\n', ' | '))
    all_output.append(f'  Exit: {ec}')
    all_exit |= ec

with open(LOG, 'w', encoding='utf-8') as f:
    f.write('\n'.join(all_output))

print('\n'.join(all_output))
print(f'\n\n=== EXIT CODE: {all_exit} (0=all pass, nonzero=failures) ===')
print(f'Full log: {LOG}')
sys.exit(all_exit)
