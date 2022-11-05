from hashlib import md5
import os
from pathlib import Path
from typing import Mapping, Optional
from kgdata.wikidata.models import WDClass, WDProperty


ROOT_DIR = Path(__file__).parent.parent.absolute()
DB_DIR = (
    Path(__file__).parent.parent.parent / "data/home/databases"
    if os.environ.get("DB_DIR") is None
    else Path(os.environ["DB_DIR"])
)
assert DB_DIR.exists()


def get_class_readable_label(
    eid: str,
    wdredirections: Optional[Mapping[str, str]] = None,
    wdclasses: Optional[Mapping[str, WDClass]] = None,
):
    if wdclasses is None:
        return None

    if wdredirections is not None and eid in wdredirections:
        eid = wdredirections[eid]

    return f"{wdclasses[eid].label} ({eid})"


def get_prop_readable_label(
    pid: str,
    wdredirections: Optional[Mapping[str, str]] = None,
    wdprops: Optional[Mapping[str, WDProperty]] = None,
):
    if wdprops is None:
        return None

    if wdredirections is not None and pid in wdredirections:
        pid = wdredirections[pid]

    return f"{wdprops[pid].label} ({pid})"
