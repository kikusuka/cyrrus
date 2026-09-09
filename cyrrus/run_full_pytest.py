import sys
sys.path.insert(0, r'c:\Users\DELL\Downloads\cyrrus\cyrrus')

import subprocess
import os

os.chdir(r'c:\Users\DELL\Downloads\cyrrus\cyrrus')

result = subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/', '-v', '--tb=short',
     '--no-header', '-p', 'no:warnings'],
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace'
)

output_path = r'c:\Users\DELL\Downloads\cyrrus\cyrrus\full_pytest_output.txt'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('STDOUT:\n')
    f.write(result.stdout)
    f.write('\n\nSTDERR:\n')
    f.write(result.stderr)
    f.write(f'\n\nReturn code: {result.returncode}\n')

# Also write a summary
passed = 0
failed = 0
errors = 0
last_line = ''
for line in result.stdout.split('\n'):
    last_line = line
    if ' passed' in line:
        parts = line.split()
        for p in parts:
            if p.isdigit() and 'passed' in line:
                try:
                    passed = int(p)
                except:
                    pass
    if ' failed' in line:
        parts = line.split()
        for i, p in enumerate(parts):
            if p == 'failed' and i > 0:
                try:
                    failed = int(parts[i-1])
                except:
                    pass
    if ' error' in line:
        parts = line.split()
        for i, p in enumerate(parts):
            if p == 'error' and i > 0:
                try:
                    errors = int(parts[i-1])
                except:
                    pass

print('Summary line:', last_line)
print(f'Passed: {passed}')
print(f'Failed: {failed}')
print(f'Errors: {errors}')
print(f'Total: {passed + failed + errors}')
print(f'\nFull output written to: {output_path}')
print(f'Return code: {result.returncode}')

if result.returncode != 0:
    # Show failures
    print('\n=== FAILURES ===')
    in_fail = False
    for line in result.stdout.split('\n'):
        if 'FAILURES' in line or 'FAILED ' in line:
            in_fail = True
        if in_fail:
            print(line)
        if ' short test summary info' in line:
            break
    for line in result.stdout.split('\n'):
        if 'FAILED ' in line:
            print(line)
