from core.store.composite import CompositeStore
from core.store.sqlite_store import SQLiteStore


def _build(name: str, settings):
    if name == "sqlite":
        return SQLiteStore(settings.sqlite_path)
    if name == "sheets":
        from core.store.sheets_store import SheetsStore
        return SheetsStore(settings.sheets_credentials_file, settings.sheet_url)
    raise ValueError(f"Unknown store backend: {name}")


def get_store(settings) -> CompositeStore:
    primary = _build(settings.store_primary, settings)
    mirrors = [_build(n, settings) for n in settings.store_mirrors if n != settings.store_primary]
    return CompositeStore(primary, mirrors)
