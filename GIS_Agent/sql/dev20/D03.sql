-- D03 L1: 统计与含孔洞的施工区 A003 相交、状态为正常的燃气设备数量，孔洞内的设备不计入，边界接触计入。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 孔洞不属于施工区实体；相交包含边界。
WITH a AS (SELECT geom FROM gis_lab.construction_areas WHERE code='A003') SELECT jsonb_build_object('count',count(*)) AS answer FROM gis_lab.gas_devices d CROSS JOIN a WHERE d.status IN ('正常') AND ST_Intersects(d.geom,a.geom);
