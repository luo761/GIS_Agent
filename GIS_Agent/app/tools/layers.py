from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayerSpec:
    name: str
    schema_name: str
    table_name: str
    geom_column: str = "geom"
    id_column: str = "id"
    code_column: str = "code"
    label_column: str = "name"
    public_columns: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


ALLOWED_LAYERS: dict[str, LayerSpec] = {
    "construction_areas": LayerSpec(
        name="construction_areas",
        schema_name="gis_lab",
        table_name="construction_areas",
        public_columns=("id", "code", "name", "area_type", "note"),
    ),
    "gas_pipelines": LayerSpec(
        name="gas_pipelines",
        schema_name="gis_lab",
        table_name="gas_pipelines",
        public_columns=("id", "code", "name", "pipe_type", "pressure_level", "note"),
    ),
    "gas_devices": LayerSpec(
        name="gas_devices",
        schema_name="gis_lab",
        table_name="gas_devices",
        public_columns=("id", "code", "name", "device_type", "status", "note"),
    ),
    "water_pipelines": LayerSpec(
        name="water_pipelines",
        schema_name="gis_lab",
        table_name="water_pipelines",
        public_columns=("id", "code", "name", "pipe_type", "note"),
    ),
    "demo_roads": LayerSpec(
        name="demo_roads",
        schema_name="gis_lab",
        table_name="demo_roads",
        public_columns=("id", "code", "name", "road_type", "note"),
    ),
}


def get_layer_spec(layer_name: str) -> LayerSpec:
    try:
        return ALLOWED_LAYERS[layer_name]
    except KeyError as exc:
        allowed = ", ".join(sorted(ALLOWED_LAYERS))
        raise ValueError(f"不允许访问的空间图层: {layer_name}。允许值: {allowed}") from exc
