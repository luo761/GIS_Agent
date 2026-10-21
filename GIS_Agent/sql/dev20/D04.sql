-- D04 L1: 查询全部状态为正常的燃气设备，按 device_type 分组计数，按设备类型名称升序输出全部分组。
-- 独立只读基准；EPSG:3857、quad_segs=8；不调用工具或执行器。
-- 不加空间限制；只统计正常设备；同一设备只计一次；名称按 Unicode 顺序。
WITH grouped AS (SELECT device_type AS label,count(*) AS value,count(*) AS n FROM gis_lab.gas_devices WHERE status='正常' GROUP BY device_type) SELECT jsonb_build_object('groups',COALESCE(jsonb_agg(jsonb_build_object('group',jsonb_build_object('device_type',label),'value',value,'feature_count',n) ORDER BY label COLLATE "C"),'[]'::jsonb),'unit','feature') AS answer FROM grouped;
