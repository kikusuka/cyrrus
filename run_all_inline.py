import sys
import os

WORK_DIR = r'c:\Users\DELL\Downloads\cyrrus\cyrrus'
sys.path.insert(0, WORK_DIR)
os.chdir(WORK_DIR)

import pytest

TEST_FILES = [
    'tests/test_stemmer.py',
    'tests/test_backend.py',
    'tests/test_bm25.py',
    'tests/test_v1.py',
    'tests/test_temporal_memory.py',
    'tests/test_edge_cases_simple.py',
    'tests/test_fact_extractor_tiers.py',
    'tests/test_embedding_router.py',
    'tests/test_adversarial.py',
    'tests/test_session_locks.py',
    'tests/test_failsafe.py',
    'tests/test_cli.py',
    'tests/test_compression.py',
    'tests/test_config_validation.py',
    'tests/test_threshold_calibration.py',
    'tests/test_token_consistency.py',
    'tests/test_streaming.py',
]

LOG = r'c:\Users\DELL\Downloads\cyrrus\all_pytest_results.log'
lines_out = []

def log(s):
    lines_out.append(str(s))

total_passed = 0
total_failed = 0
total_errors = 0
total_collected = 0

for tf in TEST_FILES:
    if not os.path.exists(os.path.join(WORK_DIR, tf)):
        log(f'SKIP (not found): {tf}')
        continue
    log(f'\n=== {tf} ===')
    try:
        result = pytest.main([
            tf, '-v', '--tb=line', '-p', 'no:warnings',
            '--no-header', '-q',
        ])
        log(f'  pytest exit: {result}')
    except Exception as e:
        log(f'  EXCEPTION: {type(e).__name__}: {e}')

# Run ALL tests together for a combined count
log('\n\n=============== COMBINED RUN ===============')
try:
    all_args = [
        'tests/', '-v', '--tb=line', '-p', 'no:warnings',
        '--no-header', '-q',
    ]
    result = pytest.main(all_args)
    log(f'Combined pytest exit: {result}')
except Exception as e:
    log(f'Combined EXCEPTION: {type(e).__name__}: {e}')

with open(LOG, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines_out))

print('\n'.join(lines_out[-50:]))
print(f'\nFull log: {LOG}')
