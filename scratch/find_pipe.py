import os
import re

def search_pipes():
    pattern = re.compile(r':\s*[^#\n]*\|')
    for root, dirs, files in os.walk('.'):
        if '.git' in root or '.venv' in root or 'brain' in root or 'scratch' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    for idx, line in enumerate(lines):
                        # Simple check for '|' in type annotations
                        if ':' in line and '|' in line:
                            # Verify if it is likely a type hint
                            # (avoid bitwise OR inside statements)
                            if any(x in line for x in ['def ', 'class ', ' = ']) or line.strip().startswith('def '):
                                print(f"{path}:{idx+1}: {line.strip()}")
                except Exception as e:
                    print(f"Error reading {path}: {e}")

if __name__ == "__main__":
    search_pipes()
