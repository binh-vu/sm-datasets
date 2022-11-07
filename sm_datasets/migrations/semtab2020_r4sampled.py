from __future__ import annotations


from sm.dataset import Dataset
from sm_datasets.helper import (
    ROOT_DIR,
)
from sm_datasets.datasets import Datasets


def migrate():
    examples = Datasets().semtab2020r4()
    table_ids = set()
    for path in (ROOT_DIR / "semtab2020_r4sampled" / "tables").glob("*.json"):
        table_ids.add(path.stem)

    selected_examples = [e for e in examples if e.table.table.table_id in table_ids]
    assert len(selected_examples) == len(table_ids)

    Dataset(ROOT_DIR / "semtab2020_r4sampled").save(
        selected_examples, clean_previous_data=False, table_fmt_indent=2
    )


if __name__ == "__main__":
    migrate()
