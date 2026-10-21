-- D10 L2: 计算施工区 A001 与 A002 交集的长度（米）；两区仅共边时，返回公共边界长度而不是面积。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 明确 length；面面交集可能退化为线，不把零面积当作空交集。
WITH common AS (SELECT ST_Intersection(a.geom,b.geom) AS geom FROM gis_lab.construction_areas a CROSS JOIN gis_lab.construction_areas b WHERE a.code='A001' AND b.code='A002') SELECT jsonb_build_object('length',jsonb_build_object('value',ST_Length(geom),'unit','meter','measure','length','measure_srid',3857,'is_empty',ST_IsEmpty(geom))) AS answer FROM common;
