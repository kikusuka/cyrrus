import sys
import subprocess
import os

# Use absolute paths everywhere
TEST_DIR = r'c:\Users\DELL\Downloads\cyrrus\cyrrus\tests'
WORK_DIR = r'c:\Users\DELL\Downloads\cyrrus\cyrrus'
OUT_PATH = r'c:\Users\DELL\Downloads\cyrrus\cyrrus\pytest_out.log'

sys.path.insert(0, WORK_DIR)
os.chdir(WORK_DIR)

cmd = [
    sys.executable, '-m', 'pytest',
    TEST_DIR,
    '-v',
    '--tb=short',
    '-p', 'no:warnings',
    '-q',
]

print(f'Running: {" ".join(cmd)}')
sys.stdout.flush()

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=WORK_DIR,
)
out_bytes, _ = proc.communicate()
out_text = out_bytes.decode('utf-8', errors='replace')

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    f.write(out_text)
    f.write(f'\n\nExit code: {proc.returncode}\n')

print(out_text[-4000:] if len(out_text) > 4000 else out_text)
print(f'\nFull output saved to: {OUT_PATH}')
sys.exit(proc.returncode)
