from __future__ import annotations
from collections import defaultdict
from collections.abc import Set, Mapping
import pandas as pd
from pathlib import Path
from typing import Any
from kgdata.wikidata.models.wdentity import WDEntity
from loguru import logger
import orjson
from sm.dataset import Dataset, Example, FullTable
from sm.inputs.link import WIKIDATA, EntityId, Link
from sm.namespaces.namespace import KnowledgeGraphNamespace
from sm.namespaces.wikidata import WikidataNamespace
from sm.outputs.semantic_model import ClassNode, LiteralNode, LiteralNodeDataType

ROOT_DIR = Path(__file__).parent.parent.absolute()


class Datasets:
    def wt250(self, fix_el: bool = True):
        dataset = Dataset(ROOT_DIR / "250wt")
        examples = dataset.load()
        if fix_el:
            for file in (dataset.location / "el_corrections/tables").iterdir():
                if not file.name.endswith(".tsv"):
                    continue

                with open(file, "r") as stream:
                    table_id = orjson.loads(stream.readline())
                    table = [
                        ex for ex in examples if ex.table.table.table_id == table_id
                    ][0].table
                    df = pd.read_csv(
                        stream,
                        sep="\t",
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
                            link = Link(
                                start=row["start"],
                                end=row["end"],
                                url=row["url"],
                                entities=[EntityId(row["entity"], WIKIDATA)],
                            )
                            links.append(link)
                        table.links[ri, ci] = links
        return examples

    def semtab2020r4(self):
        return Dataset(ROOT_DIR / "semtab2020_round4").load()

    def semtab2020r4_sampled50(self):
        return Dataset(ROOT_DIR / "semtab2020_r4sampled").load()

    def semtab2020r4_sampled512(self):
        examples = {e.table.table.table_id: e for e in self.semtab2020r4()}
        return [
            examples[eid]
            for eid in orjson.loads(
                (ROOT_DIR / "semtab2020_round4/sampled_4k.json").read_bytes()
            )[:512]
        ]

    def biotable(self):
        return Dataset(ROOT_DIR / "biotables").load()

    def biotable_rowsampled200(self):
        examples = {e.table.table.table_id: e for e in self.biotable()}
        for eid, sample in orjson.loads(
            (ROOT_DIR / "biotables" / "sampled_rows.json").read_bytes()
        ).items():
            examples[eid].table.keep_rows(sample[:200])
        return list(examples.values())

    def fix_redirection(
        self,
        examples: list[Example[FullTable]],
        entities: Mapping[str, WDEntity] | Set[str],
        redirections: Mapping[str, str],
        kgns: KnowledgeGraphNamespace,
    ):
        for example in examples:
            table = example.table
            for cell in table.links.flat_iter():
                for link in cell:
                    link.entities = self._fix_redirections(
                        link.entities, entities, redirections
                    )

            table.context.page_entities = self._fix_redirections(
                table.context.page_entities, entities, redirections
            )

            for sm in example.sms:
                for n in sm.iter_nodes():
                    if isinstance(n, ClassNode) and kgns.is_abs_uri_entity(n.abs_uri):
                        qid = kgns.get_entity_id(n.abs_uri)
                        if qid not in entities:
                            # if the qid not in redirection, the class is deleted, we should consider remove this example
                            new_qid = redirections[qid]
                            logger.debug("Redirect entity: {} to {}", qid, new_qid)

                            assert (
                                new_qid in entities
                            ), "Just to be safe that qnodes & redirections are consistent"
                            n.abs_uri = kgns.get_entity_abs_uri(new_qid)
                            n.rel_uri = kgns.get_entity_rel_uri(new_qid)
                    if isinstance(n, LiteralNode):
                        if n.datatype == LiteralNodeDataType.Entity:
                            qid = WikidataNamespace.get_entity_id(n.value)
                            if qid not in entities:
                                # if the qid not in redirection, the class is deleted, we should consider remove this example
                                new_qid = redirections[qid]
                                logger.debug("Redirect entity: {} to {}", qid, new_qid)

                                assert (
                                    new_qid in entities
                                ), "Just to be safe that qnodes & redirections are consistent"
                                n.value = WikidataNamespace.get_entity_abs_uri(new_qid)

        return examples

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
                assert (
                    newid is None or newid in entities
                ), "Just to be safe that qnodes & redirections are consistent"
                if newid is not None:
                    newents.append(EntityId(newid, entid.type))
            else:
                newents.append(entid)
        return newents


if __name__ == "__main__":
    # exs = Datasets().wt250()
    exs = Datasets().biotable()
    print(len(exs))
