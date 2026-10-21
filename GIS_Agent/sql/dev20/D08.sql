-- D08 L2: 以燃气设备 D011 为中心建立 300 米缓冲区，计算缓冲区位于 A001 内的面积（平方米）。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 圆弧固定 quad_segs=8；只计算 A001 内覆盖，不用 πr² 代替实际缓冲面积。
WITH a AS (SELECT geom FROM gis_lab.construction_areas WHERE code='A001'), clipped AS (SELECT ST_Intersection(ST_Buffer(d.geom,300,'quad_segs=8'),a.geom) AS geom FROM gis_lab.gas_devices d CROSS JOIN a WHERE d.code='D011') SELECT jsonb_build_object('area',jsonb_build_object('value',ST_Area(geom),'unit','square_meter','measure','area','measure_srid',3857,'is_empty',ST_IsEmpty(geom))) AS answer FROM clipped;
