-- D02 L1: 统计与施工区 A001 相交、状态为正常或告警的燃气设备数量，包含边界设备，同一设备只计一次。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 包含边界；状态条件为正常 OR 告警。
WITH a AS (SELECT geom FROM gis_lab.construction_areas WHERE code='A001') SELECT jsonb_build_object('count',count(*)) AS answer FROM gis_lab.gas_devices d CROSS JOIN a WHERE d.status IN ('正常','告警') AND ST_Intersects(d.geom,a.geom);
