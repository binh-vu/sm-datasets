from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Set
from pathlib import Path
from typing import Any

import orjson
import pandas as pd
from kgdata.models.ont_property import OntologyProperty
from loguru import logger
from sm.dataset import Dataset, Example, FullTable
from sm.inputs.link import EntityId, Link
from sm.misc.funcs import filter_duplication
from sm.namespaces.namespace import KnowledgeGraphNamespace
from sm.namespaces.utils import KGName
from sm.namespaces.wikidata import WikidataNamespace
from sm.outputs.semantic_model import ClassNode, LiteralNode, LiteralNodeDataType

ROOT_DIR = Path(__file__).parent.parent.absolute()
DATASET_DIR = Path(__file__).parent / "datasets"


class FixedELDataset(Dataset):
    def load(self):
        examples = super().load()
        for file in (self.location / "el_corrections/tables").iterdir():
            if file.name.endswith(".tsv"):
                delimiter = "\t"
            elif file.name.endswith(".csv"):
                delimiter = ","
            else:
                continue

            with open(file, "r") as stream:
                table_id = orjson.loads(stream.readline())
                (ex,) = [
                    ex_ for ex_ in examples if ex_.table.table.table_id == table_id
                ]
                table = ex.table
                df = pd.read_csv(
                    stream,
                    sep=delimiter,
                    dtype={
                        "url": str,
                        "row": int,
                        "col": int,
                        "start": int,
                        "end": int,
                        "entity": str,
                    },
                )
                df[["url"]] = df[["url"]].fillna("")
                pos2rows = defaultdict(list)
                for row in df.to_dict(orient="records"):
                    ri, ci = row["row"], row["col"]
                    pos2rows[ri, ci].append(row)

                for (ri, ci), rows in pos2rows.items():
                    links = []
                    for row in rows:
                        if row["entity"] == "":
                            # so we can remove links for a cell by setting entity to empty
                            continue
                        link = Link(
                            start=row["start"],
                            end=row["end"],
                            url=row["url"],
                            entities=[EntityId(row["entity"], KGName.Wikidata)],
                        )
                        links.append(link)
                    table.links[ri, ci] = links
        return examples


class Datasets:
    def get_dataset(self, name: str) -> Dataset:
        return getattr(self, name)()

    def wt250(self, fix_el: bool = True):
        if fix_el:
            return FixedELDataset(DATASET_DIR / "250wt")
        return Dataset(DATASET_DIR / "250wt")

    def semtab2022_r1(self):
        return Dataset(DATASET_DIR / "semtab2022_hardtable_r1")

    def semtab2023_r1(self):
        return Dataset(DATASET_DIR / "semtab2023_wikitables_r1")

    def semtab2019_t2dv2_dbpedia(self):
        return Dataset(DATASET_DIR / "semtab2019_t2dv2/dbpedia")

    def semtab2020r4(self):
        return Dataset(DATASET_DIR / "semtab2020_round4")

    def semtab2020r4_sampled50(self):
        return Dataset(DATASET_DIR / "semtab2020_r4sampled")

    def semtab2020r4_sampled512(self):
        examples = {e.table.table.table_id: e for e in self.semtab2020r4().load()}
        return [
            examples[eid]
            for eid in orjson.loads(
                (DATASET_DIR / "semtab2020_round4/sampled_4k.json").read_bytes()
            )[:512]
        ]

    def semtab2024_wikitables_r1_valid(self):
        return Dataset(DATASET_DIR / "semtab2024_wikitables_r1/valid")

    def semtab2024_wikitables_r1_test(self):
        return Dataset(DATASET_DIR / "semtab2024_wikitables_r1/test")

    def semtab2024_wikitables_r2_test(self):
        return Dataset(DATASET_DIR / "semtab2024_wikitables_r2/test")

    def biotable(self):
        return Dataset(DATASET_DIR / "biotables")

    def t2dv2(self):
        return Dataset(DATASET_DIR / "t2dv2")

    def biotable_rowsampled200(self):
        examples = {e.table.table.table_id: e for e in self.biotable().load()}
        for eid, sample in orjson.loads(
            (DATASET_DIR / "biotables" / "sampled_rows.json").read_bytes()
        ).items():
            examples[eid].table = examples[eid].table.select_rows(sample[:200])
        return list(examples.values())

    def fix_redirection(
        self,
        examples: list[Example[FullTable]],
        entity_labels: Mapping[str, str] | Set[str],
        props: Mapping[str, OntologyProperty] | Set[str],
        redirections: Mapping[str, str],
        kgns: KnowledgeGraphNamespace,
        skip_unk_ont_ent: bool = False,
        skip_no_sm: bool = False,
    ):
        new_examples: list[Example[FullTable]] = []
        for example in examples:
            table = example.table
            for cell in table.links.flat_iter():
                for link in cell:
                    link.entities = self._fix_redirections(
                        link.entities, entity_labels, redirections
                    )

            table.context.entities = self._fix_redirections(
                table.context.entities, entity_labels, redirections
            )

            new_sms = []
            for sm_i, sm in enumerate(example.sms):
                skip_sm = False
                for n in sm.iter_nodes():
                    if isinstance(n, ClassNode):
                        assert kgns.is_uri(n.abs_uri)
                        if kgns.is_uri_in_main_ns(n.abs_uri):
                            qid = kgns.uri_to_id(n.abs_uri)
                            if qid not in entity_labels:
                                # if the qid not in redirection, the class is deleted, we should consider remove this example
                                new_qid = redirections[qid]
                                logger.debug("Redirect entity: {} to {}", qid, new_qid)

                                assert new_qid in entity_labels, (
                                    "Just to be safe that qnodes & redirections are consistent",
                                    new_qid,
                                )
                                n.abs_uri = kgns.id_to_uri(new_qid)
                                n.rel_uri = kgns.get_rel_uri(kgns.id_to_uri(new_qid))

                                if kgns.has_encrypted_name(n.abs_uri) and isinstance(
                                    entity_labels, Mapping
                                ):
                                    n.readable_label = (
                                        f"{entity_labels[new_qid]} ({new_qid})"
                                    )
                                else:
                                    n.readable_label = None

                    if isinstance(n, LiteralNode):
                        if n.datatype == LiteralNodeDataType.Entity:
                            assert kgns.is_uri(n.value)
                            qid = kgns.uri_to_id(n.value)
                            if qid not in entity_labels:
                                # if the qid not in redirection, the class is deleted, we should consider remove this example
                                new_qid = redirections[qid]
                                logger.debug("Redirect entity: {} to {}", qid, new_qid)

                                assert new_qid in entity_labels, (
                                    "Just to be safe that entities & redirections are consistent",
                                    new_qid,
                                )
                                n.value = kgns.id_to_uri(new_qid)

                                if kgns.has_encrypted_name(n.value) and isinstance(
                                    entity_labels, Mapping
                                ):
                                    n.readable_label = (
                                        f"{entity_labels[new_qid]} ({new_qid})"
                                    )
                                else:
                                    n.readable_label = None

                pid = None
                for e in sm.iter_edges():
                    assert kgns.is_uri(e.abs_uri)
                    if not kgns.is_uri_in_main_ns(e.abs_uri):
                        continue
                    pid = kgns.uri_to_id(e.abs_uri)
                    if pid not in props:
                        if pid in redirections:
                            new_pid = redirections[pid]
                            logger.debug("Redirect property: {} to {}", pid, new_pid)

                            assert new_pid in props, (
                                "Just to be safe that entities & redirections are consistent",
                                new_pid,
                            )
                            e.abs_uri = kgns.id_to_uri(new_pid)
                            e.rel_uri = kgns.get_rel_uri(kgns.id_to_uri(new_pid))

                            if kgns.has_encrypted_name(e.abs_uri) and isinstance(
                                props, Mapping
                            ):
                                e.readable_label = f"{props[new_pid].label} ({new_pid})"
                            else:
                                e.readable_label = None  # we leverage the default label is rel_uri -- so no need to assign it here.
                        else:
                            if skip_unk_ont_ent:
                                # if the pid not in redirection, the property is deleted, we should consider remove this example
                                skip_sm = True
                                break
                            else:
                                raise KeyError("Unknown property", pid)

                if skip_sm and skip_unk_ont_ent:
                    logger.debug(
                        "Skip the semantic model at pos {} of example {} due to unknown property {}",
                        sm_i,
                        example.table.table.table_id,
                        pid,
                    )
                    continue
                new_sms.append(sm)

            example.sms = new_sms
            if len(example.sms) == 0 and skip_no_sm:
                logger.debug(
                    "Skip the example {} due to no semantic model",
                    example.table.table.table_id,
                )
                continue
            new_examples.append(example)

        return new_examples

    def _fix_redirections(
        self,
        entids: list[EntityId],
        entities: Mapping[str, Any] | Set[str],
        redirections: Mapping[str, str],
    ) -> list[EntityId]:
        newents = []
        for entid in entids:
            if entid not in entities:
                newid = redirections.get(entid, None)
                logger.debug("Redirect entity: {} to {}", entid, newid)
                assert newid is None or newid in entities, (
                    "Just to be safe that entities & redirections are consistent",
                    newid,
                )
                if newid is not None:
                    newents.append(EntityId(newid, entid.type))
            else:
                newents.append(entid)

        # we need to filter duplicated entities because datasets such as semtab2019-t2dv2 generates lots of duplications
        return filter_duplication(newents)


if __name__ == "__main__":
    # exs = Datasets().wt250()
    exs = Datasets().biotable().load()
    print(len(exs))
