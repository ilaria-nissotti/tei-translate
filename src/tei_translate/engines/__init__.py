"""MT engines behind one interface (see base.MTEngine). Pick one by name."""

from tei_translate.engines.identity import IdentityEngine, TagEngine

ENGINES = {"identity": IdentityEngine, "tag": TagEngine}


def get_engine(name: str):
    try:
        return ENGINES[name]()
    except KeyError:
        raise ValueError(f"unknown engine {name!r}; available: {', '.join(sorted(ENGINES))}") from None
