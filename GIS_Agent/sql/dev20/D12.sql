-- D12 L2: 计算所有水管位于孤立施工区 A009 内的总长度（米），并返回非空裁剪结果的源水管数量。若没有匹配水管，长度和数量都返回 0，不报目标不存在。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- A009 存在；匹配集合为空是成功结果，不使用缺失目标替代空结果。
WITH a AS (SELECT geom FROM gis_lab.construction_areas WHERE code='A009'), cut AS (SELECT ST_Intersection(w.geom,a.geom) AS geom FROM gis_lab.water_pipelines w CROSS JOIN a WHERE ST_Intersects(w.geom,a.geom)), retained AS (SELECT geom FROM cut WHERE NOT ST_IsEmpty(geom)) SELECT jsonb_build_object('length',jsonb_build_object('value',COALESCE(sum(ST_Length(geom)),0),'unit','meter','measure','length','measure_srid',3857,'feature_count',count(*))) AS answer FROM retained;
