-- D07 L2: 计算所有水管位于施工区 A003 实体部分内的总长度（米），排除孔洞，包含边界接触，并返回非空裁剪结果的源水管数量。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 先相交筛选再裁剪；点接触长度为零但仍计为非空源记录；不做几何 union。
WITH a AS (SELECT geom FROM gis_lab.construction_areas WHERE code='A003'), cut AS (SELECT ST_Intersection(w.geom,a.geom) AS geom FROM gis_lab.water_pipelines w CROSS JOIN a WHERE ST_Intersects(w.geom,a.geom)), retained AS (SELECT geom FROM cut WHERE NOT ST_IsEmpty(geom)) SELECT jsonb_build_object('length',jsonb_build_object('value',COALESCE(sum(ST_Length(geom)),0),'unit','meter','measure','length','measure_srid',3857,'feature_count',count(*))) AS answer FROM retained;
