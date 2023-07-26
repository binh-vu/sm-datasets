"""Converting SemTab datasets into sem-desc format."""
from __future__ import annotations

import csv
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import asdict, dataclass
from glob import glob
from io import StringIO
from pathlib import Path
from typing import List, Literal, Mapping, Optional, Tuple, Union, cast
from zipfile import ZipFile

import orjson
import pandas as pd
import serde.csv
import serde.json
import serde.textline
import yada
from kgdata.wikidata.db import (
    WikidataDB,
    get_class_db,
    get_entity_redirection_db,
    get_prop_db,
)
from kgdata.wikidata.models import WDClass, WDProperty
from loguru import logger
from rdflib import RDFS
from sm.dataset import Context, FullTable
from sm.inputs.link import WIKIDATA, EntityId, Link
from sm.misc.matrix import Matrix
from sm.namespaces.wikidata import WikidataNamespace
from sm.prelude import I, M, O
from tqdm import tqdm

PathOrStr = Union[str, Path]


@dataclass
class CEA:
    row: int
    col: int
    ent_uris: list[str]


@dataclass
class CTA:
    col: int
    type_uri: str


@dataclass
class CPA:
    source: int
    target: int
    prop_uri: str


class SemTab(ABC):
    def __init__(
        self,
        indir: Path,
        outdir: Path,
        ont: Ontology,
        unk_cta_handler: Literal["ignore", "skip", "error"],
    ):
        self.indir = indir
        self.outdir = outdir
        self.ont = ont
        self.unk_cta_handler = unk_cta_handler

    def normalize(
        self,
    ):
        """Normalize semtab2022 dataset. This function tested on HardTablesR1.

        The original semtab2022 dataset should have the following format:

        The output will have the following format:
        descriptions
        ├── part-<num>.zip
        │   ├── <table_file_name>.json
        tables
        ├── part-<num>.zip
        │   ├── <table_file_name>.json

        Args:
            indir: the original Round_<num> directory
            outdir: the output directory
        """
        table2cea = self.get_table2cea()
        table2cta = self.get_table2cta()
        table2cpa = self.get_table2cpa()

        outputs: List[Tuple[O.SemanticModel, FullTable]] = []

        # verifying that the target and ground truth are the same
        target_cea = self.get_target_cea()
        target_cta = self.get_target_cta()
        target_cpa = self.get_target_cpa()

        assert len(set(target_cea.keys()).symmetric_difference(table2cea.keys())) == 0
        assert len(set(target_cta.keys()).symmetric_difference(table2cta.keys())) == 0
        assert len(set(target_cpa.keys()).symmetric_difference(table2cpa.keys())) == 0

        for table_id, lst in table2cea.items():
            assert (
                set(target_cea[table_id]).symmetric_difference(
                    [(x.row, x.col) for x in lst]
                )
                == set()
            )

        for table_id, lst in table2cta.items():
            assert (
                set(target_cta[table_id]).symmetric_difference([x.col for x in lst])
                == set()
            )

        for table_id, lst in table2cpa.items():
            assert (
                set(target_cpa[table_id]).symmetric_difference(
                    [(x.source, x.target) for x in lst]
                )
                == set()
            )

        print("Number of tables:")
        print(
            "- CEA ground-truth: #tables =",
            len(table2cea),
            ", #entities =",
            sum(len(lst) for lst in table2cea.values()),
        )
        print(
            "- CTA ground-truth: #tables =",
            len(table2cta),
            ", #entity-columns =",
            sum(len(lst) for lst in table2cta.values()),
        )
        print(
            "- CPA ground-truth: #tables =",
            len(table2cpa),
            ", #relationships = ",
            sum(len(lst) for lst in table2cpa.values()),
        )

        # extract tables
        print("- # CSV File:", sum(1 for _ in (self.indir / "tables").glob("*.csv")))
        ignore_logs = []

        for file in tqdm(sorted((self.indir / "tables").glob("*.csv"))):
            table_id = file.stem
            if table_id not in table2cta:
                assert table_id not in table2cpa
                continue

            with open(file, mode="r") as f:
                reader = csv.reader(f, delimiter=",")
                lst = [row for row in reader]
                header, rows = lst[0], lst[1:]
                columns = []
                for ci in range(len(header)):
                    columns.append(
                        I.Column(
                            index=ci, name=header[ci], values=[row[ci] for row in rows]
                        )
                    )

                table = I.ColumnBasedTable(table_id=table_id, columns=columns)
                shp = table.shape()
                links = [[[] for ci in range(shp[1])] for ri in range(shp[0])]
                for cea in table2cea[table_id]:
                    links[cea.row][cea.col].append(
                        Link(
                            start=0,
                            end=len(table[cea.row, cea.col]),
                            url=None,
                            entities=[
                                self.ont.get_entity_id(uri) for uri in cea.ent_uris
                            ],
                        )
                    )

                sm = O.SemanticModel()
                col2node = {}
                for col in table.columns:
                    col2node[col.index] = sm.add_node(
                        O.DataNode(col.index, cast(str, col.name))
                    )

                assert table_id in table2cta
                rels = table2cpa.get(table_id, [])
                types = table2cta[table_id]
                ignore_table = False

                for cta in types:
                    try:
                        label = self.ont.get_class_readable_label(cta.type_uri)
                    except KeyError:
                        logger.error(
                            "Table {} contains unknown class {} in column {}",
                            table_id,
                            cta.type_uri,
                            cta.col,
                        )
                        label = None
                        if self.unk_cta_handler == "ignore":
                            ignore_table = True
                            ignore_logs.append(
                                f"Ignore table {table_id} as it contains unknown class {cta.type_uri} in column {cta.col}"
                            )
                            break
                        elif self.unk_cta_handler == "error":
                            raise

                    class_id = sm.add_node(
                        O.ClassNode(
                            abs_uri=self.ont.get_entity_abs_uri(cta.type_uri),
                            rel_uri=self.ont.get_entity_rel_uri(cta.type_uri),
                            approximation=False,
                            readable_label=label,
                        )
                    )
                    sm.add_edge(
                        O.Edge(
                            source=class_id,
                            target=col2node[cta.col],
                            abs_uri=str(RDFS.label),
                            rel_uri=self.ont.get_rel_uri(RDFS.label),
                            approximation=False,
                            readable_label=self.ont.get_rel_uri(RDFS.label),
                        )
                    )
                    col2node[cta.col] = class_id

                if ignore_table:
                    continue

                for cpa in rels:
                    pid = cpa.prop_uri
                    c1, c2 = cpa.source, cpa.target
                    try:
                        label = self.ont.get_prop_readable_label(cpa.prop_uri)
                    except KeyError:
                        logger.error(
                            "Table {} contains unknown property {} from column {} -> {}",
                            table_id,
                            cpa.prop_uri,
                            c1,
                            c2,
                        )
                        label = None
                        if self.unk_cta_handler == "ignore":
                            ignore_table = True
                            ignore_logs.append(
                                f"Ignore table {table_id} as it contains unknown property {cpa.prop_uri} from column {c1} -> {c2}"
                            )
                            break

                    source_node = sm.get_node(col2node[c1])
                    if not (
                        isinstance(source_node, O.ClassNode)
                        or (
                            isinstance(source_node, O.LiteralNode)
                            and source_node.datatype == O.LiteralNodeDataType.Entity
                        )
                    ):
                        ignore_table = True
                        ignore_logs.append(
                            f"Ignore table {table_id} as it contains edge from column {c1} -> {c2} but {c1} is not a class or entity node"
                        )
                        break
                    sm.add_edge(
                        O.Edge(
                            source=col2node[c1],
                            target=col2node[c2],
                            abs_uri=self.ont.get_prop_abs_uri(pid),
                            rel_uri=self.ont.get_prop_rel_uri(pid),
                            approximation=False,
                            readable_label=label,
                        )
                    )

                if ignore_table:
                    continue

                outputs.append(
                    (sm, FullTable(table=table, context=Context(), links=Matrix(links)))
                )

        serde.textline.ser(ignore_logs, self.outdir / "ignore_tables.log")

        outputs = sorted(outputs, key=lambda x: x[1].table.table_id)
        (self.outdir / "descriptions").mkdir(exist_ok=True, parents=True)
        (self.outdir / "tables").mkdir(exist_ok=True, parents=True)

        batch_size = 500

        # compress the content to save space, use zless, zcat to browse it
        serde.csv.ser(
            [
                [table_id, self.ser_semtab_row_index(row), str(col)]
                for table_id, lst in target_cea.items()
                for row, col in lst
            ],
            self.outdir / f"cea_targets.csv.gz",
        )
        serde.csv.ser(
            [
                [table_id, str(col)]
                for table_id, lst in target_cta.items()
                for col in lst
            ],
            self.outdir / f"cta_targets.csv.gz",
        )
        serde.csv.ser(
            [
                [table_id, str(source), str(target)]
                for table_id, lst in target_cpa.items()
                for source, target in lst
            ],
            self.outdir / f"cpa_targets.csv.gz",
        )

        counter = 0
        for i in range(0, len(outputs), batch_size):
            batch = outputs[i : i + batch_size]
            filename = f"part-{counter:04d}.zip"
            with ZipFile(self.outdir / "descriptions" / filename, "w") as zf:
                for sm, table in batch:
                    zf.writestr(
                        table.table.table_id + ".json",
                        data=orjson.dumps([sm.to_dict()]),
                    )
            with ZipFile(self.outdir / "tables" / filename, "w") as zf:
                for sm, table in batch:
                    zf.writestr(
                        table.table.table_id + ".json",
                        data=orjson.dumps(table.to_dict()),
                    )
            counter += 1

    def get_table2cea(self) -> dict[str, list[CEA]]:
        rows = serde.csv.deser(self.get_gt_cea_file())
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 4
            table_id, ri, ci = row[0], int(row[1]) - 1, int(row[2])
            ent_uris = row[3].split(" ")
            output[table_id].append(CEA(row=ri, col=ci, ent_uris=ent_uris))
        return dict(output)

    def get_table2cta(self) -> dict[str, list[CTA]]:
        rows = serde.csv.deser(self.get_gt_cta_file())
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 3, row
            table_id = row[0]
            output[table_id].append(CTA(col=int(row[1]), type_uri=row[2]))
        return dict(output)

    def get_table2cpa(self) -> dict[str, list[CPA]]:
        rows = serde.csv.deser(self.get_gt_cpa_file())
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 4
            table_id = row[0]
            output[table_id].append(
                CPA(source=int(row[1]), target=int(row[2]), prop_uri=row[3])
            )
        return dict(output)

    def get_target_cea(self) -> dict[str, list[tuple[int, int]]]:
        rows = serde.csv.deser(self.get_target_cea_file())
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 3
            table_id, ri, ci = row[0], self.deser_semtab_row_index(row[1]), int(row[2])
            output[table_id].append((ri, ci))
        return dict(output)

    def get_target_cta(self) -> dict[str, list[int]]:
        rows = serde.csv.deser(self.get_target_cta_file())
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 2
            if row[0] == "" and row[1] == "":
                # encounter this error on semtab t2dv2
                continue
            table_id, col = row[0], int(row[1])
            output[table_id].append(col)
        return dict(output)

    def get_target_cpa(self) -> dict[str, list[tuple[int, int]]]:
        cpa_file = self.get_target_cpa_file()
        assert cpa_file is not None
        rows = serde.csv.deser(cpa_file)
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 2
            table_id, source, target = row[0], int(row[1]), int(row[2])
            output[table_id].append((source, target))
        return dict(output)

    def deser_semtab_row_index(self, row_index: str) -> int:
        # semtab row starts from 1 instead of 0
        return int(row_index) - 1

    def ser_semtab_row_index(self, row_index: int) -> str:
        # semtab row starts from 1 instead of 0
        return str(row_index + 1)

    @abstractmethod
    def get_gt_cea_file(self) -> Path:
        ...

    @abstractmethod
    def get_gt_cta_file(self) -> Path:
        ...

    @abstractmethod
    def get_gt_cpa_file(self) -> Path:
        ...

    @abstractmethod
    def get_target_cea_file(self) -> Path:
        ...

    @abstractmethod
    def get_target_cta_file(self) -> Path:
        ...

    @abstractmethod
    def get_target_cpa_file(self) -> Optional[Path]:
        ...


class SemTab2019(SemTab):
    def get_table2cea(self) -> dict[str, list[CEA]]:
        rows = serde.csv.deser(self.get_gt_cea_file())
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 4
            # in semtab t2d dataset, column first, then row
            table_id, ci, ri = row[0], int(row[1]), int(row[2]) - 1
            ent_uris = row[3].split(" ")
            output[table_id].append(CEA(row=ri, col=ci, ent_uris=ent_uris))
        return dict(output)

    def get_target_cea(self) -> dict[str, list[tuple[int, int]]]:
        rows = serde.csv.deser(self.get_target_cea_file())
        output = defaultdict(list)
        for row in rows:
            assert len(row) == 3
            # in semtab t2d dataset, column first, then row
            table_id, ci, ri = row[0], int(row[1]), int(row[2]) - 1
            output[table_id].append((ri, ci))
        return dict(output)

    def get_target_cpa(self) -> dict[str, list[tuple[int, int]]]:
        if self.get_target_cpa_file() is None:
            assert (
                str(self.indir).find("t2dv2") != -1
            ), "t2dv2 dataset don't have CPA target file"
            # use the gt file as target
            return {
                table_id: [(x.source, x.target) for x in lst]
                for table_id, lst in self.get_table2cpa().items()
            }

        return super().get_target_cpa()

    def get_gt_cea_file(self) -> Path:
        # make sure only one file matches the pattern
        (infile,) = glob(str(self.indir / "gt/CEA_*_gt.csv"))
        return Path(infile)

    def get_gt_cta_file(self) -> Path:
        # make sure only one file matches the pattern
        (infile,) = glob(str(self.indir / "gt/CTA_*_gt.csv"))
        return Path(infile)

    def get_gt_cpa_file(self) -> Path:
        # make sure only one file matches the pattern
        (infile,) = glob(str(self.indir / "gt/CPA_*_gt.csv"))
        return Path(infile)

    def get_target_cea_file(self) -> Path:
        # make sure only one file matches the pattern
        (infile,) = glob(str(self.indir / "targets/CEA_*_Targets.csv"))
        return Path(infile)

    def get_target_cta_file(self) -> Path:
        # make sure only one file matches the pattern
        (infile,) = glob(str(self.indir / "targets/CTA_*_Targets.csv"))
        return Path(infile)

    def get_target_cpa_file(self) -> Optional[Path]:
        # make sure only one file matches the pattern
        infiles = glob(str(self.indir / "targets/CPA_*_Targets.csv"))
        if len(infiles) == 0:
            return None
        else:
            assert len(infiles) == 1
            return Path(infiles[0])


class Ontology(ABC):
    @abstractmethod
    def get_prop_readable_label(self, prop_uri: str) -> str:
        ...

    @abstractmethod
    def get_class_readable_label(
        self,
        class_uri: str,
    ) -> str:
        ...

    @abstractmethod
    def get_entity_id(self, ent_uri: str) -> EntityId:
        ...

    @abstractmethod
    def get_entity_abs_uri(self, ent_uri: str) -> str:
        ...

    @abstractmethod
    def get_entity_rel_uri(self, ent_uri: str) -> str:
        ...

    @abstractmethod
    def get_prop_abs_uri(self, prop_uri: str) -> str:
        ...

    @abstractmethod
    def get_prop_rel_uri(self, prop_uri: str) -> str:
        ...

    @abstractmethod
    def get_rel_uri(self, uri: str) -> str:
        ...


class WikidataOntology(Ontology):
    def __init__(self, db: WikidataDB):
        self.db = db
        self.wdns = WikidataNamespace.create()

    def get_entity_id(self, ent_uri: str) -> EntityId:
        return EntityId(self.wdns.get_entity_id(ent_uri), WIKIDATA)

    def get_prop_readable_label(
        self,
        prop_uri: str,
    ):
        pid = self.wdns.get_prop_id(prop_uri)
        if pid in self.db.redirections:
            pid = self.db.redirections[pid]

        return f"{self.db.props[pid].label} ({pid})"

    def get_class_readable_label(
        self,
        class_uri: str,
    ):
        eid = self.wdns.get_entity_id(class_uri)
        if eid in self.db.redirections:
            eid = self.db.redirections[eid]

        return f"{self.db.classes[eid].label} ({eid})"

    def get_entity_abs_uri(self, ent_uri: str) -> str:
        return self.wdns.get_entity_abs_uri(self.wdns.get_entity_id(ent_uri))

    def get_entity_rel_uri(self, ent_uri: str) -> str:
        return self.wdns.get_entity_rel_uri(self.wdns.get_entity_id(ent_uri))

    def get_prop_abs_uri(self, prop_uri: str) -> str:
        return self.wdns.get_prop_abs_uri(self.wdns.get_prop_id(prop_uri))

    def get_prop_rel_uri(self, prop_uri: str) -> str:
        return self.wdns.get_prop_rel_uri(self.wdns.get_prop_id(prop_uri))

    def get_rel_uri(self, uri: str) -> str:
        return self.wdns.get_rel_uri(uri)


class DBpediaOntology(Ontology):
    def get_prop_readable_label(self, prop_uri: str) -> str:
        return prop_uri

    def get_class_readable_label(
        self,
        class_uri: str,
    ) -> str:
        return class_uri

    def get_entity_id(self, ent_uri: str) -> EntityId:
        return EntityId(ent_uri, "dbpedia")

    def get_entity_abs_uri(self, ent_uri: str) -> str:
        return ent_uri

    def get_entity_rel_uri(self, ent_uri: str) -> str:
        return ent_uri

    def get_prop_abs_uri(self, prop_uri: str) -> str:
        return prop_uri

    def get_prop_rel_uri(self, prop_uri: str) -> str:
        return prop_uri

    def get_rel_uri(self, uri: str) -> str:
        return uri


@dataclass
class CLI:
    database_dir: Path
    input_dir: Path
    output_dir: Path

    ontology: Literal["wikidata", "dbpedia"]
    unk_cta_handler: Literal["ignore", "skip", "error"] = "error"


if __name__ == "__main__":
    cli = yada.Parser1(CLI).parse_args()

    if cli.ontology == "wikidata":
        ont = WikidataOntology(WikidataDB(cli.database_dir))
    else:
        assert cli.ontology == "dbpedia"
        ont = DBpediaOntology()

    if not cli.output_dir.exists():
        cli.output_dir.mkdir(parents=True)
        metadata = {
            "ontology": cli.ontology,
            "unk_cta_handler": cli.unk_cta_handler,
        }
        if (cli.output_dir / "metadata.json").exists():
            assert metadata == serde.json.deser(cli.output_dir / "metadata.json")
        else:
            serde.json.ser(metadata, cli.output_dir / "metadata.json")
    SemTab2019(cli.input_dir, cli.output_dir, ont, cli.unk_cta_handler).normalize()
