INSERT INTO gis_lab.construction_areas (code, name, area_type, note, geom) VALUES
('A001', '施工一区', '施工区', '1000m x 1000m 正方形，便于手算。', ST_GeomFromText('POLYGON((0 0,1000 0,1000 1000,0 1000,0 0))', 3857)),
('A002', '施工二区', '施工区', '与施工一区共边。', ST_GeomFromText('POLYGON((1000 0,2000 0,2000 1000,1000 1000,1000 0))', 3857)),
('A003', '施工三区含孔洞', '施工区', '外环 1000m x 1000m，中心 200m x 200m 孔洞。', ST_GeomFromText('POLYGON((0 1000,1000 1000,1000 2000,0 2000,0 1000),(400 1400,600 1400,600 1600,400 1600,400 1400))', 3857)),
('A004', '远端施工区', '施工区', '用于不相交测试。', ST_GeomFromText('POLYGON((2200 0,2800 0,2800 600,2200 600,2200 0))', 3857)),
('A005', '西南小施工区', '施工区', '400m x 400m 小区域。', ST_GeomFromText('POLYGON((-500 -500,-100 -500,-100 -100,-500 -100,-500 -500))', 3857)),
('A006', '北侧施工区', '施工区', '与施工三区相邻。', ST_GeomFromText('POLYGON((0 2000,1000 2000,1000 2600,0 2600,0 2000))', 3857)),
('A007', '东侧施工区', '施工区', '用于跨区道路和管线测试。', ST_GeomFromText('POLYGON((2000 0,2600 0,2600 1000,2000 1000,2000 0))', 3857)),
('A008', '狭长施工区', '施工区', '宽 200m 的狭长区域。', ST_GeomFromText('POLYGON((300 300,1500 300,1500 500,300 500,300 300))', 3857)),
('A009', '孤立测试区', '施工区', '远离其他模拟业务要素。', ST_GeomFromText('POLYGON((3200 1200,3800 1200,3800 1800,3200 1800,3200 1200))', 3857)),
('A010', '边界接触测试区', '施工区', '南边界 y=1000，测试边界接触。', ST_GeomFromText('POLYGON((1200 1000,1800 1000,1800 1600,1200 1600,1200 1000))', 3857));

INSERT INTO gis_lab.gas_pipelines (code, name, pipe_type, pressure_level, note, geom) VALUES
('G001', '一区东西向燃气管线', '燃气管线', '中压', '完全位于施工一区，长度 800m。', ST_GeomFromText('LINESTRING(100 100,900 100)', 3857)),
('G002', '跨一区二区燃气管线', '燃气管线', '中压', '跨越施工一区和施工二区，长度 1200m。', ST_GeomFromText('LINESTRING(400 500,1600 500)', 3857)),
('G003', '边界接触燃气管线', '燃气管线', '低压', '沿施工一区北边界，仅接触边界。', ST_GeomFromText('LINESTRING(0 1000,1000 1000)', 3857)),
('G004', '南北向交叉燃气管线', '燃气管线', '高压', '与 G002 十字相交，穿过施工一区。', ST_GeomFromText('LINESTRING(500 -200,500 1200)', 3857)),
('G005', '远端燃气管线', '燃气管线', '低压', '用于不相交测试。', ST_GeomFromText('LINESTRING(3000 3000,3400 3000)', 3857)),
('G006', '孔洞穿越燃气管线', '燃气管线', '中压', '穿过施工三区孔洞，裁剪测量时可观察孔洞影响。', ST_GeomFromText('LINESTRING(100 1500,900 1500)', 3857)),
('G007', '二区竖向燃气管线', '燃气管线', '中压', '完全位于施工二区。', ST_GeomFromText('LINESTRING(1500 100,1500 900)', 3857)),
('G008', '东侧燃气管线', '燃气管线', '低压', '位于东侧施工区。', ST_GeomFromText('LINESTRING(2100 100,2500 900)', 3857)),
('G009', '折线燃气管线', '燃气管线', '中压', '多顶点折线，测试长度累加。', ST_GeomFromText('LINESTRING(100 300,300 300,300 700,700 700)', 3857)),
('G010', '斜穿一区燃气管线', '燃气管线', '高压', '斜穿施工一区，长度可用勾股核对。', ST_GeomFromText('LINESTRING(0 0,1000 1000)', 3857)),
('G011', '北侧燃气管线', '燃气管线', '低压', '位于北侧施工区。', ST_GeomFromText('LINESTRING(100 2100,900 2100)', 3857)),
('G012', '西南燃气管线', '燃气管线', '低压', '位于西南小施工区。', ST_GeomFromText('LINESTRING(-450 -300,-150 -300)', 3857));

INSERT INTO gis_lab.gas_devices (code, name, device_type, status, note, geom) VALUES
('D001', '一区阀门一', '阀门', '正常', '施工一区内。', ST_GeomFromText('POINT(100 100)', 3857)),
('D002', '一区调压站', '调压站', '正常', '施工一区内。', ST_GeomFromText('POINT(800 800)', 3857)),
('D003', '二区阀门一', '阀门', '正常', '施工二区内。', ST_GeomFromText('POINT(1200 500)', 3857)),
('D004', '孔洞内设备', '阀门', '正常', '位于施工三区孔洞内，不应 ST_Within 施工三区。', ST_GeomFromText('POINT(500 1500)', 3857)),
('D005', '施工三区设备', '阀门', '正常', '施工三区实体部分内。', ST_GeomFromText('POINT(200 1500)', 3857)),
('D006', '边界设备', '阀门', '正常', '位于施工一区边界。', ST_GeomFromText('POINT(1000 500)', 3857)),
('D007', '远端设备', '阀门', '停用', '不与主要施工区相交。', ST_GeomFromText('POINT(3300 1500)', 3857)),
('D008', '西南设备', '阀门', '正常', '西南小施工区内。', ST_GeomFromText('POINT(-300 -300)', 3857)),
('D009', '北侧设备', '调压站', '正常', '北侧施工区内。', ST_GeomFromText('POINT(500 2300)', 3857)),
('D010', '东侧设备', '阀门', '正常', '东侧施工区内。', ST_GeomFromText('POINT(2300 400)', 3857)),
('D011', '一区泄漏演示点', '监测点', '告警', '用于近邻查询演示。', ST_GeomFromText('POINT(520 520)', 3857)),
('D012', '二区监测点', '监测点', '正常', '用于近邻排序演示。', ST_GeomFromText('POINT(1700 800)', 3857));

INSERT INTO gis_lab.water_pipelines (code, name, pipe_type, note, geom) VALUES
('W001', '一区南北向给水管线', '给水', '与多条燃气管线相交。', ST_GeomFromText('LINESTRING(500 -100,500 1100)', 3857)),
('W002', '二区斜向排水管线', '排水', '位于施工二区。', ST_GeomFromText('LINESTRING(1100 100,1900 900)', 3857)),
('W003', '远端给水管线', '给水', '不相交测试。', ST_GeomFromText('LINESTRING(3600 3000,3900 3000)', 3857)),
('W004', '孔洞穿越给水管线', '给水', '穿过施工三区孔洞。', ST_GeomFromText('LINESTRING(500 1100,500 1900)', 3857)),
('W005', '西南排水管线', '排水', '位于西南小施工区。', ST_GeomFromText('LINESTRING(-450 -450,-150 -150)', 3857)),
('W006', '东侧给水管线', '给水', '位于东侧施工区。', ST_GeomFromText('LINESTRING(2300 100,2300 900)', 3857)),
('W007', '北侧排水管线', '排水', '位于北侧施工区。', ST_GeomFromText('LINESTRING(100 2400,900 2400)', 3857)),
('W008', '狭长区给水管线', '给水', '位于狭长施工区内。', ST_GeomFromText('LINESTRING(300 400,1500 400)', 3857)),
('W009', '边界接触水管线', '给水', '沿施工二区北边界。', ST_GeomFromText('LINESTRING(1000 1000,2000 1000)', 3857)),
('W010', '折线水管线', '排水', '多顶点折线。', ST_GeomFromText('LINESTRING(1200 200,1400 200,1400 600,1800 600)', 3857));

INSERT INTO gis_lab.demo_roads (code, name, road_type, note, geom) VALUES
('R001', '跨一区二区道路', '城市道路', '模拟道路跨越两个施工区，不是真实 OSM 数据。', ST_GeomFromText('LINESTRING(200 250,1800 250)', 3857)),
('R002', '穿越东侧道路', '城市道路', '跨越施工二区和东侧施工区。', ST_GeomFromText('LINESTRING(1700 700,2500 700)', 3857)),
('R003', '远端道路', '城市道路', '不相交测试。', ST_GeomFromText('LINESTRING(3000 100,3600 100)', 3857));

INSERT INTO gis_lab.invalid_geometry_cases (code, name, expected_problem, geom) VALUES
('INV001', '自相交蝴蝶面', 'ST_IsValid 应返回 false。', ST_GeomFromText('POLYGON((0 0,100 100,100 0,0 100,0 0))', 3857)),
('INV002', '重复点线', '长度为 0 或接近 0，用于边界测试。', ST_GeomFromText('LINESTRING(10 10,10 10)', 3857));

INSERT INTO gis_lab.srid_input_examples (code, name, source_srid, target_srid, geom) VALUES
('SRID001', 'WGS84 输入点', 4326, 3857, ST_SetSRID(ST_MakePoint(114.3055, 30.5928), 4326)),
('SRID002', 'WebMercator 输入点', 3857, 3857, ST_GeomFromText('POINT(500 500)', 3857));

INSERT INTO gis_lab.import_batches (
    source_type,
    source_name,
    original_crs,
    target_srid,
    imported_count,
    invalid_geometry_count,
    metadata
) VALUES (
    'mock',
    'phase1_seed',
    'EPSG:3857',
    3857,
    0,
    0,
    '{"description": "模拟数据批次，和真实 OSM/外部数据明确区分。"}'::jsonb
);
