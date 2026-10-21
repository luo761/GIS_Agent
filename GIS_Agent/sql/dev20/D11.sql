-- D11 L2: 计算施工区 A001 与狭长施工区 A008 的重叠面积（平方米）。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 仅交集面积，不计算两个区面积之和或 union 面积。
WITH overlap AS (SELECT ST_Intersection(a.geom,b.geom) AS geom FROM gis_lab.construction_areas a CROSS JOIN gis_lab.construction_areas b WHERE a.code='A001' AND b.code='A008') SELECT jsonb_build_object('area',jsonb_build_object('value',ST_Area(geom),'unit','square_meter','measure','area','measure_srid',3857,'is_empty',ST_IsEmpty(geom))) AS answer FROM overlap;
