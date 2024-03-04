from __future__ import annotations

import html
from io import StringIO, TextIOWrapper
from pathlib import Path

import orjson
import serde.csv
import serde.json
from rdflib import RDFS
from rsoup.core import ContentHierarchy, RichText
from serde.helper import fix_encoding
from sm.dataset import Dataset, Example, FullTable
from sm.namespaces.prelude import Namespace
from sm.prelude import I, M, O

dsdir = Path(__file__).parent.parent / "datasets/t2dv2"
ns = Namespace.from_prefix2ns(
    {"dbpedia": "http://dbpedia.org/ontology/", "rdfs": str(RDFS)}
)

manually_verified_colprops = {
    x[0] for x in serde.csv.deser(dsdir / "verified_col_property_name.csv")[1:]
}
manually_verified_table_data = {
    x[0]: {
        "skip": x[1] == "1",
        "no_header": x[2] == "1",
        "headers": {} if x[3] == "" else orjson.loads(x[3]),
    }
    for x in serde.csv.deser(dsdir / "verified_table_header.csv")[1:]
}


def parse_table(table_id: str, raw_tbl: dict, logfile: TextIOWrapper) -> FullTable:
    if (
        raw_tbl["tableType"] != "RELATION"
        and table_id not in manually_verified_table_data
    ):
        logfile.write(
            f"[ParseError] Table ID: {table_id}. Unknown supported table type: {raw_tbl['tableType']}\n"
        )

    if (
        not (
            raw_tbl["hasHeader"]
            and raw_tbl["headerPosition"] == "FIRST_ROW"
            and raw_tbl["headerRowIndex"] == 0
        )
        and table_id not in manually_verified_table_data
    ):
        logfile.write(f"[ParseError] Table ID: {table_id}. Unknown header position.\n")

    tbl = I.ColumnBasedTable(table_id, [])

    for ci, col in enumerate(raw_tbl["relation"]):
        if table_id in manually_verified_table_data:
            if manually_verified_table_data[table_id]["no_header"]:
                cname = ""
                cvals = col
            else:
                # we verified that the header is in the first row
                cname = col[0]
                cvals = col[1:]

            if str(ci) in manually_verified_table_data[table_id]["headers"]:
                cname = manually_verified_table_data[table_id]["headers"][str(ci)]
        else:
            # always assume the first row is the header -- will manually verify this later.
            cname = col[0]
            cvals = col[1:]

        tbl.columns.append(I.Column(ci, cname, cvals))

    tbl = tbl.remove_empty_rows()

    return FullTable(
        tbl,
        I.Context(
            raw_tbl["pageTitle"],
            raw_tbl["url"],
            content_hierarchy=[
                ContentHierarchy.from_dict(
                    {
                        "level": 1,
                        "heading": RichText.from_str("").to_dict(),
                        "content_before": [
                            RichText.from_str(raw_tbl["textBeforeTable"]).to_dict()
                        ],
                        "content_after": [
                            RichText.from_str(raw_tbl["textAfterTable"]).to_dict()
                        ],
                    }
                )
            ],
        ),
        M.Matrix.default(tbl.shape(), list),
    )


def migrate_t2dv2(indir: Path, logfile: TextIOWrapper):

    if not (indir / "_FIXED_ENCODING").exists():
        for file in (indir / "tables").iterdir():
            if file.name.startswith("."):
                continue
            assert file.suffix == ".json"
            fix_encoding(file)

        (indir / "_FIXED_ENCODING").touch()

    # parse id 2 class
    def norm_class_dep(row):
        assert row[0].endswith(".tar.gz")
        row[0] = row[0][: -len(".tar.gz")]
        row[-1] = row[-1].replace("http://dbpedia_org", "http://dbpedia.org")
        return row

    id2class = {
        k: M.assert_one_item(rows)[2]
        for k, rows in M.group_by(
            map(norm_class_dep, serde.csv.deser(indir / "classes_GS.csv")),
            lambda row: row[0],
        ).items()
    }
    examples = []
    id2table = {}

    for file in (indir / "tables").iterdir():
        if file.name.startswith("."):
            continue

        table_id = file.stem
        if table_id not in id2class:
            continue

        if not (indir / f"property/{table_id}.csv").exists():
            # no property
            continue

        if (
            table_id in manually_verified_table_data
            and manually_verified_table_data[table_id]["skip"]
        ):
            # manually skip the table -- because either the model is incorrect or it's not a relational table
            continue

        col_props = serde.csv.deser(indir / f"property/{table_id}.csv")
        if len(col_props) == 0:
            # no property
            continue

        assert file.suffix == ".json"

        # parse table
        tbl = parse_table(table_id, serde.json.deser(file), logfile)

        # create semantic description
        sm = O.SemanticModel()

        uid = sm.add_node(
            O.ClassNode(id2class[table_id], ns.get_rel_uri(id2class[table_id]))
        )
        for col in col_props:
            ci = int(col[-1])
            cname = tbl.table.columns[ci].name
            assert cname is not None
            cname = cname.strip()
            if (
                cname.lower() != html.unescape(col[1]).strip()
                and table_id not in manually_verified_colprops
            ):
                logfile.write(
                    f"[ColPropError] Table ID: {table_id}."
                    + f" Inconsistent column name: (index = {ci}) `{cname}` vs `{col[1].strip()}`\n",
                )

            vid = sm.add_node(O.DataNode(ci, cname))
            sm.add_edge(O.Edge(uid, vid, col[0], ns.get_rel_uri(col[0])))

        examples.append(Example(id=table_id, sms=[sm], table=tbl))
        id2table[table_id] = dict(id=table_id, **serde.json.deser(file))

    Dataset(indir.parent).save(examples, table_fmt="txt")
    return


if __name__ == "__main__":
    with open(dsdir / "convert.log", "w") as logfile:
        migrate_t2dv2(dsdir / "raw_data", logfile)
