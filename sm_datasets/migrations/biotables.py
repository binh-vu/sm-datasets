from __future__ import annotations

from collections import defaultdict
import csv
from io import StringIO
from typing import Dict, List, Mapping, Optional, cast
from zipfile import ZipFile
from kgdata.wikidata.db import (
    WikidataDB,
)
from kgdata.wikidata.models import WDClass, WDProperty
from loguru import logger
from rdflib import RDFS

from sm.dataset import Dataset, Example, FullTable
import sm.inputs.prelude as I
import sm.outputs.semantic_model as O
from sm.misc.matri
x import Matrix
from sm.namespaces.wikidata import WikidataNamespace
from sm_datasets.helper import (
    DB_DIR,
    ROOT_DIR,
    get_class_readable_label,
    get_prop_readable_label,
)
from tqdm import tqdm
from pathlib import Path


def normalize_biotables(
    dataset_name="biotables",
    wdredirections: Optional[Mapping[str, str]] = None,
    wdclasses: Optional[Mapping[str, WDClass]] = None,
    wdprops: Optional[Mapping[str, WDProperty]] = None,
):
    ds = Dataset(ROOT_DIR / dataset_name)
    file = ds.location / "raw_data" / "BioTable-Datasets.zip"
    wdns = WikidataNamespace.create()
    ignore_logs = []
    ignore_tables = set()

    with ZipFile(file) as zf:
        tables: Dict[str, I.ColumnBasedTable] = {}
        table2links: Dict[str, Matrix[List[I.Link]]] = {}
        table2sm: Dict[str, O.SemanticModel] = {}

        gt_tasks = defaultdict(list)
        for file in tqdm(zf.infolist(), desc="parsing tables"):
            if file.filename.startswith("datasets"):
                table_id = Path(file.filename).stem
                with zf.open(file, mode="r") as f:
                    reader = csv.reader(StringIO(f.read().decode()), delimiter=",")
                    rows = [row for row in reader]
                    tables[table_id] = I.ColumnBasedTable.from_rows(
                        rows, table_id, strict=True
                    )
            else:
                assert file.filename.startswith("ground-truth"), file.filename
                assert file.filename.endswith(".csv")

                task = Path(file.filename).name[:3]
                gt_tasks[task].append(file)

        assert set(gt_tasks.keys()) == {"cea", "cpa", "cta"}
        gt_tasks = {k: gt_tasks[k] for k in ["cta", "cpa", "cea"]}
        table2col2node = {}
        for task, files in gt_tasks.items():
            gt, gt_target = sorted(files, key=lambda f: f.filename)
            with zf.open(gt, mode="r") as f:
                reader = csv.reader(StringIO(f.read().decode()), delimiter=",")
                gt_rows = [row for row in reader]
            with zf.open(gt_target, mode="r") as f:
                reader = csv.reader(StringIO(f.read().decode()), delimiter=",")
                gt_target_rows = [row for row in reader]

            assert len(gt_rows) == len(gt_target_rows)
            assert all(
                (x[0], x[-1]) == (y[0], y[-1]) for x, y in zip(gt_rows, gt_target_rows)
            )

            table2rows = defaultdict(list)
            for row in tqdm(gt_rows, desc=f"parsing {task} (step 1)"):
                table2rows[row[0]].append(row[1:])
            for tid, rows in tqdm(table2rows.items(), desc=f"parsing {task} (step 2)"):
                table = tables[tid]
                if task == "cea":
                    table2links[tid] = Matrix.default(table.shape(), lambda: list())
                    for ri, ci, wdenturl in rows:
                        table2links[tid][int(ri), int(ci)].append(
                            I.Link(
                                start=0,
                                end=len(table[int(ri), int(ci)]),
                                url=wdenturl,
                                entities=[
                                    I.EntityId(wdns.get_entity_id(wdenturl), "wikidata")
                                ],
                            )
                        )
                elif task == "cta":
                    assert tid not in table2sm
                    sm = O.SemanticModel(check_cycle=True, multigraph=False)
                    table2sm[tid] = sm

                    col2node = {}
                    for col in table.columns:
                        col2node[col.index] = sm.add_node(
                            O.DataNode(col.index, cast(str, col.name))
                        )

                    for ci, wdenturl in rows:
                        ci = int(ci)
                        entid = wdns.get_entity_id(wdenturl)

                        try:
                            label = get_class_readable_label(
                                entid, wdredirections, wdclasses
                            )
                        except KeyError:
                            logger.error(
                                "Table {} contains unknown class {} in column {}",
                                tid,
                                entid,
                                ci,
                            )
                            label = None
                            if wdclasses is not None and wdredirections is not None:
                                ignore_tables.add(tid)
                                ignore_logs.append(
                                    f"Ignore table {tid} as it contains unknown class {entid} in column {ci}"
                                )
                                break

                        class_id = sm.add_node(
                            O.ClassNode(
                                abs_uri=wdns.get_entity_abs_uri(entid),
                                rel_uri=wdns.get_entity_rel_uri(entid),
                                approximation=False,
                                readable_label=label,
                            )
                        )
                        sm.add_edge(
                            O.Edge(
                                source=class_id,
                                target=col2node[ci],
                                abs_uri=str(RDFS.label),
                                rel_uri=wdns.get_rel_uri(RDFS.label),
                                approximation=False,
                                readable_label=wdns.get_rel_uri(RDFS.label),
                            )
                        )
                        col2node[ci] = class_id

                    table2col2node[tid] = col2node
                elif task == "cpa":
                    assert tid in table2sm
                    sm = table2sm[tid]
                    col2node = table2col2node[tid]

                    for ci, cj, wdpropurl in rows:
                        pid = wdns.get_prop_id(wdpropurl)
                        label = get_prop_readable_label(pid, wdredirections, wdprops)
                        sm.add_edge(
                            O.Edge(
                                source=col2node[int(ci)],
                                target=col2node[int(cj)],
                                abs_uri=wdns.get_prop_abs_uri(pid),
                                rel_uri=wdns.get_prop_rel_uri(pid),
                                approximation=False,
                                readable_label=label,
                            )
                        )

        examples = []
        for tid, table in tables.items():
            if tid in ignore_tables:
                ignore_logs.append("Ignore table {tid}")
                continue

            examples.append(
                Example(
                    sms=[table2sm[tid]],
                    table=FullTable(table, context=I.Context(), links=table2links[tid]),
                )
            )

        ds.save(examples, individual_table_compressed="gz")


if __name__ == "__main__":
    db = WikidataDB(DB_DIR)
    normalize_biotables(
        wdredirections=db.wdredirections.cache(),
        wdclasses=db.wdclasses.cache(),
        wdprops=db.wdprops.cache(),
    )
