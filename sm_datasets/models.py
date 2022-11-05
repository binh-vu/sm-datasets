from __future__ import annotations
from dataclasses import dataclass
from typing import List

from sm.inputs.prelude import ColumnBasedTable, Context, Link
from sm.misc.matrix import Matrix


@dataclass
class Table:
    table: ColumnBasedTable
    context: Context
    links: Matrix[List[Link]]

    def to_dict(self):
        return {
            "version": 2,
            "table": self.table.to_dict(),
            "context": self.context.to_dict(),
            "links": [
                [[link.to_dict() for link in cell] for cell in row]
                for row in self.links.data
            ],
        }

    @staticmethod
    def from_dict(obj: dict):
        version = obj["version"]
        if not (version == "1.2" or version == 2):
            raise ValueError(f"Unknown version: {version}")

        return Table(
            table=ColumnBasedTable.from_dict(obj["table"]),
            context=Context.from_dict(obj["context"]),
            links=Matrix(
                [
                    [[Link.from_dict(link) for link in cell] for cell in row]
                    for row in obj["links"]
                ]
            ),
        )
