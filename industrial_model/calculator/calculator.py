from __future__ import annotations

from datetime import datetime
from itertools import islice

from cognite.client import CogniteClient

from .datapoints_retrieval import DatapointsRetriever
from .formula_expression import evaluate
from .models import CalculationResult, CalculatorQuery, DataPoint


class Calculator:
    def __init__(self, cognite_client: CogniteClient) -> None:
        self._retriever = DatapointsRetriever(cognite_client)

    def calculate(
        self, query: CalculatorQuery, start: datetime, end: datetime
    ) -> CalculationResult:
        return self.calculate_multiples([query], start, end)[0]

    def calculate_multiples(
        self, queries: list[CalculatorQuery], start: datetime, end: datetime
    ) -> list[CalculationResult]:
        datapoints = self._retriever.retrieve_datapoints(
            [parameter for q in queries for parameter in q.parameters], start, end
        )

        it = iter(datapoints)
        return [
            self._calculate(query, list(islice(it, len(query.parameters))))
            for query in queries
        ]

    def _calculate(
        self, query: CalculatorQuery, datapoints: list[list[tuple[datetime, float]]]
    ) -> CalculationResult:
        values_map = {
            param.alias: [val for _, val in series]
            for param, series in zip(query.parameters, datapoints, strict=True)
        }

        values = evaluate(query.formula, values_map)
        first_series = datapoints[0] if datapoints else []
        timestamps = [ts for ts, _ in first_series]
        return CalculationResult(
            query=query,
            datapoints=[
                DataPoint(timestamp=ts, value=value)
                for ts, value in zip(timestamps, values, strict=True)
            ],
        )
