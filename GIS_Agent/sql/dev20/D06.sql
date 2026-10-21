-- D06 L2: 计算燃气管线 G006 位于施工区 A003 实体部分内的长度（米），排除孔洞，并返回参与量测的原管线数量。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- G006 穿过孔洞后可能分成多段，但仍是一个源要素。
WITH a AS (SELECT geom FROM gis_lab.construction_areas WHERE code='A003'), cut AS (SELECT ST_Intersection(g.geom,a.geom) AS geom FROM gis_lab.gas_pipelines g CROSS JOIN a WHERE g.code='G006'), retained AS (SELECT geom FROM cut WHERE NOT ST_IsEmpty(geom)) SELECT jsonb_build_object('length',jsonb_build_object('value',COALESCE(sum(ST_Length(geom)),0),'unit','meter','measure','length','measure_srid',3857,'feature_count',count(*))) AS answer FROM retained;
