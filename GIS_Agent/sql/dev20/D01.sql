-- D01 L1: 统计严格位于施工区 A001 内、状态为正常的燃气设备数量，边界上的设备不计入。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 严格内部，不含边界；不包含告警或停用设备。
WITH a AS (SELECT geom FROM gis_lab.construction_areas WHERE code='A001') SELECT jsonb_build_object('count',count(*)) AS answer FROM gis_lab.gas_devices d CROSS JOIN a WHERE d.status IN ('正常') AND ST_Within(d.geom,a.geom);
