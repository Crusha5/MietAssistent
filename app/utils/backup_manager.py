import os
import tempfile
import zipfile
import shutil
import signal
from typing import Callable, Optional
from flask import current_app


def progress_callback(percent: int):
    """Default progress callback used when none is provided."""
    try:
        current_app.logger.debug("Backup/Restore progress at %s%%", percent)
    except Exception:
        pass


def _count_items(base_paths):
    total = 0
    for base, prefix in base_paths:
        if not os.path.exists(base):
            continue
        for _, _, files in os.walk(base):
            total += len(files) or 0
        # Count base directory to avoid zero division
        total += 1
    return max(total, 1)


def _safe_arcname(base: str, path: str, prefix: str) -> str:
    rel_path = os.path.relpath(path, base)
    rel_path = rel_path.lstrip(os.sep)
    return os.path.join(prefix, rel_path)


def create_backup_zip(callback: Optional[Callable[[int], None]] = None) -> str:
    cb = callback or progress_callback
    upload_root = os.path.abspath(current_app.config.get('UPLOAD_ROOT', '/uploads'))
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_path = db_uri.replace('sqlite:///', '', 1) if db_uri.startswith('sqlite:///') else ''
    data_dir = os.path.dirname(db_path) if db_path else os.path.abspath('data')

    paths = [(upload_root, 'uploads'), (data_dir, 'data')]
    total_items = _count_items(paths)
    processed = 0

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    tmp_file.close()

    current_app.logger.info('Starte Backup-Erstellung: Upload-Root=%s, Data=%s, Ziel=%s', upload_root, data_dir, tmp_file.name)

    with zipfile.ZipFile(tmp_file.name, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
        for base, prefix in paths:
            if not os.path.exists(base):
                current_app.logger.warning('Pfad für Backup nicht gefunden: %s', base)
                continue
            for root, dirs, files in os.walk(base):
                # Ensure empty directories are stored
                for d in dirs:
                    dir_path = os.path.join(root, d)
                    arcname = _safe_arcname(base, dir_path, prefix) + '/'
                    zipf.writestr(arcname, '')
                for file in files:
                    abs_path = os.path.join(root, file)
                    arcname = _safe_arcname(base, abs_path, prefix)
                    zipf.write(abs_path, arcname)
                    processed += 1
                    cb(int((processed / total_items) * 100))
            processed += 1
            cb(int((processed / total_items) * 100))

    cb(100)
    current_app.logger.info('Backup erfolgreich erstellt: %s', tmp_file.name)
    return tmp_file.name


def validate_backup_zip(zip_path: str) -> tuple[bool, str]:
    if not zipfile.is_zipfile(zip_path):
        return False, 'Ungültige ZIP-Datei.'

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        names = zipf.namelist()
        has_uploads = any(name.startswith('uploads/') for name in names)
        has_data = any(name.startswith('data/') for name in names)
        if not (has_uploads and has_data):
            return False, 'ZIP muss die Verzeichnisse uploads/ und data/ enthalten.'

        for info in zipf.infolist():
            norm = os.path.normpath(info.filename)
            if os.path.isabs(norm) or norm.startswith('..'):
                return False, 'Unsicherer Pfad in ZIP erkannt.'
            if not (norm.startswith('uploads') or norm.startswith('data')):
                return False, 'ZIP darf nur uploads/ und data/ enthalten.'

    return True, 'OK'


def protected_delete_directory(target_path: str, allowed_base: str):
    target_real = os.path.realpath(target_path)
    base_real = os.path.realpath(allowed_base)
    if not target_real.startswith(base_real):
        raise ValueError('Unerlaubter Löschpfad außerhalb des erlaubten Bereichs')

    if os.path.isdir(target_real):
        for entry in os.listdir(target_real):
            entry_path = os.path.join(target_real, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
    elif os.path.exists(target_real):
        os.remove(target_real)


def _safe_extract_member(zipf: zipfile.ZipFile, member: zipfile.ZipInfo, upload_root: str, data_dir: str):
    norm = os.path.normpath(member.filename)
    if os.path.isabs(norm) or norm.startswith('..'):
        raise ValueError('Unsicherer Pfad in ZIP erkannt.')

    if norm.startswith('uploads'):
        target_base = upload_root
        relative = os.path.relpath(norm, 'uploads')
    elif norm.startswith('data'):
        target_base = data_dir
        relative = os.path.relpath(norm, 'data')
    else:
        raise ValueError('ZIP enthält unerwartete Inhalte.')

    dest_path = os.path.realpath(os.path.join(target_base, relative))
    if not dest_path.startswith(os.path.realpath(target_base)):
        raise ValueError('Pfad außerhalb des erlaubten Ziels erkannt.')

    if member.is_dir() or member.filename.endswith('/'):
        os.makedirs(dest_path, exist_ok=True)
        return

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with zipf.open(member, 'r') as src, open(dest_path, 'wb') as dst:
        shutil.copyfileobj(src, dst)


def import_backup_zip(zip_path: str, callback: Optional[Callable[[int], None]] = None) -> str:
    cb = callback or progress_callback
    upload_root = os.path.abspath(current_app.config.get('UPLOAD_ROOT', '/uploads'))
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    db_path = db_uri.replace('sqlite:///', '', 1) if db_uri.startswith('sqlite:///') else ''
    data_dir = os.path.dirname(db_path) if db_path else os.path.abspath('data')

    current_app.logger.info('Starte Backup-Import von %s', zip_path)

    valid, msg = validate_backup_zip(zip_path)
    if not valid:
        raise ValueError(msg)
    cb(5)

    emergency_backup = create_backup_zip()
    current_app.logger.info('Notfall-Backup erstellt: %s', emergency_backup)
    cb(10)

    protected_delete_directory(upload_root, upload_root)
    protected_delete_directory(os.path.join(data_dir, 'rental.db'), data_dir)
    current_app.logger.info('Bestehende Datenbereichen gelöscht für Import.')
    cb(20)

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        members = zipf.infolist()
        total = max(len(members), 1)
        for idx, member in enumerate(members, start=1):
            _safe_extract_member(zipf, member, upload_root, data_dir)
            cb(int(20 + (idx / total) * 75))

    cb(100)
    current_app.logger.info('Backup erfolgreich importiert.')
    return emergency_backup


def safe_docker_restart(flag_path: str = '/tmp/restart.flag'):
    try:
        with open(flag_path, 'w') as flag:
            flag.write('restart requested')
        current_app.logger.info('Restart-Flag geschrieben: %s', flag_path)
        return
    except Exception as exc:
        current_app.logger.warning('Konnte Restart-Flag nicht schreiben: %s', exc)

    try:
        os.kill(1, signal.SIGTERM)
        current_app.logger.info('PID 1 wurde mit SIGTERM beendet für Neustart.')
    except Exception as exc:
        current_app.logger.error('Konnte Container nicht neu starten: %s', exc)
        raise
