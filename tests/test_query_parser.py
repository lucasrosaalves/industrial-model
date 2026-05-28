from industrial_model.queries.parser import parse_filters
from industrial_model.statements import BoolExpression, LeafExpression


def test_parse_filters_builds_leaf_expressions_without_field_map() -> None:
    expressions = parse_filters(
        {
            "asset": {"eq": {"space": "my-space", "externalId": "WMT:VAL"}},
            "manufacturer": {"exists": True},
        }
    )

    assert expressions == [
        LeafExpression(
            property="asset",
            operator="==",
            value={"space": "my-space", "externalId": "WMT:VAL"},
        ),
        LeafExpression(property="manufacturer", operator="exists", value=True),
    ]


def test_parse_filters_builds_bool_expressions_without_field_map() -> None:
    expressions = parse_filters(
        {
            "OR": [
                {"tags": {"containsAny": ["critical"]}},
                {"name": {"prefix": "Compressor"}},
            ],
            "NOT": {
                "sourceId": {"eq": "legacy-system"},
            },
        }
    )

    assert expressions == [
        BoolExpression(
            operator="or",
            filters=[
                LeafExpression(
                    property="tags",
                    operator="containsAny",
                    value=["critical"],
                ),
                LeafExpression(
                    property="name",
                    operator="prefix",
                    value="Compressor",
                ),
            ],
        ),
        BoolExpression(
            operator="not",
            filters=[
                LeafExpression(
                    property="sourceId",
                    operator="==",
                    value="legacy-system",
                )
            ],
        ),
    ]


def test_parse_filters_supports_contains_all_and_contains_any() -> None:
    assert parse_filters({"tags": {"containsAny": ["critical", "safety"]}}) == [
        LeafExpression(
            property="tags",
            operator="containsAny",
            value=["critical", "safety"],
        )
    ]
    assert parse_filters({"tags": {"containsAll": ["production", "verified"]}}) == [
        LeafExpression(
            property="tags",
            operator="containsAll",
            value=["production", "verified"],
        )
    ]


def test_parse_filters_wraps_nested_filters() -> None:
    expressions = parse_filters(
        {
            "asset": {
                "AND": [
                    {"externalId": {"prefix": "WMT:"}},
                    {"space": {"eq": "my-space"}},
                ]
            }
        }
    )

    assert expressions == [
        LeafExpression(
            property="asset",
            operator="nested",
            value=BoolExpression(
                operator="and",
                filters=[
                    LeafExpression(
                        property="externalId",
                        operator="prefix",
                        value="WMT:",
                    ),
                    LeafExpression(
                        property="space",
                        operator="==",
                        value="my-space",
                    ),
                ],
            ),
        )
    ]


def test_parse_filters_wraps_super_nested_filters() -> None:
    expressions = parse_filters(
        {
            "asset": {
                "parent": {
                    "source": {
                        "OR": [
                            {"externalId": {"eq": "legacy-system"}},
                            {"externalId": {"prefix": "sap-"}},
                        ],
                    },
                    "space": {"eq": "my-space"},
                }
            }
        }
    )

    assert expressions == [
        LeafExpression(
            property="asset",
            operator="nested",
            value=LeafExpression(
                property="parent",
                operator="nested",
                value=BoolExpression(
                    operator="and",
                    filters=[
                        LeafExpression(
                            property="source",
                            operator="nested",
                            value=BoolExpression(
                                operator="or",
                                filters=[
                                    LeafExpression(
                                        property="externalId",
                                        operator="==",
                                        value="legacy-system",
                                    ),
                                    LeafExpression(
                                        property="externalId",
                                        operator="prefix",
                                        value="sap-",
                                    ),
                                ],
                            ),
                        ),
                        LeafExpression(
                            property="space",
                            operator="==",
                            value="my-space",
                        ),
                    ],
                ),
            ),
        )
    ]


def test_parse_filters_normalizes_python_style_property_names() -> None:
    assert parse_filters(
        {
            "external_id": {"eq": "asset-1"},
            "asset_type": {"exists": False},
            "class_": {"eq": "pump"},
        }
    ) == [
        LeafExpression(property="externalId", operator="==", value="asset-1"),
        BoolExpression(
            operator="not",
            filters=[
                LeafExpression(property="assetType", operator="exists", value=True)
            ],
        ),
        LeafExpression(property="class", operator="==", value="pump"),
    ]
