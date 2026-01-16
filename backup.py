import paramiko
import os
import zipfile
import datetime
import tempfile
import shutil
import glob
import fnmatch
from dotenv import load_dotenv

load_dotenv()

SFTP_HOST = os.getenv("SFTP_HOST", "example.com")
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
SFTP_USER = os.getenv("SFTP_USER", "username")
SFTP_PASSWORD = os.getenv("SFTP_PASSWORD", "password")
REMOTE_DIR = os.getenv("REMOTE_DIR", "/")
KEEP_NUM_BACKUPS = int(os.getenv("KEEP_NUM_BACKUPS", "3"))
IGNORE_CONFIG_FILE = os.getenv("IGNORE_CONFIG_FILE", "ignore_list.txt")


def load_ignore_patterns():
    ignore_patterns = []
    if os.path.exists(IGNORE_CONFIG_FILE):
        with open(IGNORE_CONFIG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    ignore_patterns.append(line)
    return ignore_patterns


def should_ignore(filename, ignore_patterns):
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def sftp_recursive_download(sftp, remote_dir, local_dir, ignore_patterns):
    os.makedirs(local_dir, exist_ok=True)

    for entry in sftp.listdir_attr(remote_dir):
        if should_ignore(entry.filename, ignore_patterns):
            print(f"Ignoring: {entry.filename}")
            continue

        print("Found", entry)
        remote_path = f"{remote_dir}/{entry.filename}"
        local_path = os.path.join(local_dir, entry.filename)

        if entry.st_mode is not None and (entry.st_mode & 0o170000) == 0o040000:
            sftp_recursive_download(sftp, remote_path, local_path, ignore_patterns)
        else:
            sftp.get(remote_path, local_path)


def cleanup_old_backups(backup_dir):
    backup_pattern = os.path.join(backup_dir, "backup-*.zip")
    backup_files = glob.glob(backup_pattern)

    if len(backup_files) > KEEP_NUM_BACKUPS:
        backup_files.sort(key=os.path.getmtime)
        files_to_delete = backup_files[:-KEEP_NUM_BACKUPS]
        for file_path in files_to_delete:
            os.remove(file_path)
            print(f"Deleted old backup: {os.path.basename(file_path)}")


def main():
    today = datetime.date.today().isoformat()
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)

    zip_name = os.path.join(backup_dir, f"backup-{today}.zip")

    temp_dir = tempfile.mkdtemp(prefix="sftp_backup_")

    ignore_patterns = load_ignore_patterns()
    print(f"Loaded {len(ignore_patterns)} ignore patterns")

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)
        if sftp is None:
            raise RuntimeError("Unable to establish SFTP connection? Are your credentials right?")

        print("Connected to SFTP")

        sftp_recursive_download(sftp, REMOTE_DIR, temp_dir, ignore_patterns)

        print("Download complete, creating zip...")

        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, temp_dir)
                    zipf.write(full_path, arcname)

        print(f"Backup created: {zip_name}")
        cleanup_old_backups(backup_dir)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            sftp.close()
            transport.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
