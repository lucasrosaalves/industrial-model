from typing import Literal

SORT_DIRECTION = Literal["ascending", "descending"]
LEAF_EXPRESSION_OPERATORS = Literal[
    "==",
    "in",
    ">=",
    ">",
    "<=",
    "<",
    "nested",
    "exists",
    "prefix",
    "containsAll",
    "containsAny",
]
BOOL_EXPRESSION_OPERATORS = Literal["not", "and", "or"]


NESTED_SEP = "|"
EDGE_MARKER = "<EdgeMarker>"
EDGE_DIRECTION = Literal["outwards", "inwards"]
MAX_LIMIT = 10_000
DEFAULT_LIMIT = 1_000
