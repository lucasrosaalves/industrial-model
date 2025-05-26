import datetime
from typing import Annotated

from pydantic import Field

from industrial_model import (
    InstanceId,
    ViewInstance,
    ViewInstanceConfig,
    WritableViewInstance,
)


class DescribableEntity(ViewInstance):
    name: str | None = None
    description: str | None = None


class ReportingSite(DescribableEntity):
    time_zone: DescribableEntity | None = None


class EventDetail(ViewInstance):
    ref_metric_code: DescribableEntity | None = None
    ref_event_code: DescribableEntity | None = None
    ref_sub_category_l1: DescribableEntity | None = None
    ref_sub_category_l2: DescribableEntity | None = None
    ref_sub_category_l3: DescribableEntity | None = None
    ref_sub_category_l4: DescribableEntity | None = None
    ref_sub_category_l5: DescribableEntity | None = None
    ref_equipment: DescribableEntity | None = None
    ref_discipline: DescribableEntity | None = None


class Event(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="OEEEvent",
        instance_spaces_prefix="OEE-",
    )

    start_date_time: datetime.datetime | None = None
    ref_site: ReportingSite | None = None
    ref_unit: DescribableEntity | None = None
    ref_reporting_line: DescribableEntity | None = None
    ref_reporting_location: DescribableEntity | None = None
    ref_product: DescribableEntity | None = None
    ref_material: DescribableEntity | None = None
    ref_process_type: DescribableEntity | None = None
    ref_oee_event_detail: Annotated[
        list[EventDetail],
        Field(default_factory=list, alias="refOEEEventDetail"),
    ]


class Msdp(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="OEEMSDP",
        instance_spaces_prefix="OEE-",
    )

    effective_date: datetime.date


class WritableEvent(WritableViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="OEEEvent",
        instance_spaces_prefix="OEE-",
    )

    start_date_time: datetime.datetime | None = None
    ref_site: ReportingSite | None = None
    ref_reporting_line: DescribableEntity | None = None
    ref_oee_event_detail: Annotated[
        list[EventDetail],
        Field(default_factory=list, alias="refOEEEventDetail"),
    ]

    def edge_id_factory(
        self, target_node: InstanceId, edge_type: InstanceId
    ) -> InstanceId:
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )
