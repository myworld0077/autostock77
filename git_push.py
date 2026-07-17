import subprocess
import sys

def run_cmd(cmd):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(result.returncode)
    print(result.stdout)

def main():
    run_cmd(["git", "add", "-A"])
    run_cmd(["git", "commit", "-m", "Fix: Allow Telegram status checks on weekends (force=True)"])
    run_cmd(["git", "push"])
    print("GitHub push completed successfully via Python 3!")

if __name__ == "__main__":
    main()
