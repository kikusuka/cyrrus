import sys
import subprocess
import os

WORK_DIR = r'c:\Users\DELL\Downloads\cyrrus\cyrrus'
os.chdir(WORK_DIR)

# Try import to check the package works
sys.path.insert(0, WORK_DIR)
try:
    import cyrrus
    print("Import OK. cyrrus version:", getattr(cyrrus, '__version__', 'unknown'))
except Exception as e:
    print(f"Import ERROR: {type(e).__name__}: {e}")
    raise

# Run a single small test first to make sure pytest works
test_file = os.path.join(WORK_DIR, 'tests', 'test_stemmer.py')
print(f"\nRunning: pytest on {test_file}...")

result = subprocess.run(
    [sys.executable, '-m', 'pytest', test_file, '-v', '--tb=short', '-p', 'no:warnings'],
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace',
    cwd=WORK_DIR,
    timeout=120
)

LOG_PATH = r'c:\Users\DELL\Downloads\cyrrus\stemmer_test.log'
with open(LOG_PATH, 'w', encoding='utf-8') as f:
    f.write("=== STDOUT ===\n")
    f.write(result.stdout)
    f.write("\n=== STDERR ===\n")
    f.write(result.stderr)
    f.write(f"\nExit code: {result.returncode}\n")

# Print last 2000 chars
output = result.stdout + "\n" + result.stderr
print(output[-3000:] if len(output) > 3000 else output)
print(f"\nExit: {result.returncode}. Full log: {LOG_PATH}")
