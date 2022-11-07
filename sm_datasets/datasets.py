from __future__ import annotations
from collections.abc import Set, Mapping

from pathlib import Path
from typing import Any
from kgdata.wikidata.models.wdentity import WDEntity
from loguru import logger
from sm.dataset import Dataset, Example, FullTable
from sm.inputs.link import EntityId
from sm.namespaces.namespace import KnowledgeGraphNamespace
from sm.namespaces.wikidata import WikidataNamespace
from sm.outputs.semantic_model import ClassNode, LiteralNode, LiteralNodeDataType

ROOT_DIR = Path(__file__).parent.parent.absolute()


class Datasets:
    def wt250(self):
        return Dataset(ROOT_DIR / "250wt").load()

    def semtab2020r4(self):
        return Dataset(ROOT_DIR / "semtab2020_round4").load()

    def semtab2020r4sampled(self):
        return Dataset(ROOT_DIR / "semtab2020_r4sampled").load()

    def biotable(self):
        return Dataset(ROOT_DIR / "biotables").load()

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
