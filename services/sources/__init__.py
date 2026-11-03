import importlib
import pkgutil

from services.sources.base import JobSource, RawJob

REGISTRY: dict[str, type[JobSource]] = {}


def register_source(cls: type[JobSource]) -> type[JobSource]:
    REGISTRY[cls.name] = cls
    return cls


def load_sources() -> dict[str, type[JobSource]]:
    """Import every module in this package so their @register_source decorators run."""
    for mod in pkgutil.iter_modules(__path__):
        if mod.name != "base":
            importlib.import_module(f"{__name__}.{mod.name}")
    return REGISTRY


__all__ = ["JobSource", "RawJob", "register_source", "load_sources", "REGISTRY"]
