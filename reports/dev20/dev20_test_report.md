# dev20 基准测试报告：多智能体 GIS 任务架构

- 生成时间：2026-11-06 15:52:58
- 被测系统：五阶段多智能体任务架构（能力可进化），仓库 `Test/`
- 模型：`deepseek-chat`
- 数据库：`localhost:5433/gis_agent`（Docker `postgis/postgis:16-3.4-alpine`，schema `gis_lab`）
- 题集：`postgis_dev20_v1`，共 20 题（L1/L2/L3）
- 作答方式：每题一次作答，失败不重规划（max_replans=0）
- 总耗时：258.4 秒

## 1. 测试环境与数据

数据通过 Docker 本地的 PostGIS 容器加载：

```text
docker run -d --name gis-postgis -p 5433:5432 \
  -e POSTGRES_USER=gis_user -e POSTGRES_PASSWORD=*** \
  -e POSTGRES_DB=gis_agent postgis/postgis:16-3.4-alpine
psql -f sql/001_extensions_and_schema.sql   # 建库（postgis / pgcrypto、gis_lab schema）
psql -f sql/002_seed_mock_data.sql          # 种子数据
```

| 图层 | 要素数 | 说明 |
| --- | --- | --- |
| construction_areas | 10 | 施工区（A003 含孔洞） |
| gas_pipelines | 12 | 燃气管线，含压力等级 |
| gas_devices | 12 | 燃气设备，含运行状态 |
| water_pipelines | 10 | 给排水管线 |
| demo_roads | 3 | 道路 |

标准答案使用题集自带的独立 SQL 快照核对；本次评测不读取参考计划或标准 SQL，只把题目与输出契约交给智能体。

## 2. 总体结果

| 指标 | 数值 |
| --- | --- |
| 正确率 | **18/20（90.0%）** |
| 平均单题耗时 | 12.9 秒（中位数 12.2 秒） |
| 平均工具调用 | 3.8 次/题（合计 75 次） |
| 初始均等导致随机路由 | 1 题 |
| 未产出 JSON | 0 题 |
| 执行异常 | 0 题 |

按难度：

| 等级 | 正确/总数 | 正确率 |
| --- | --- | --- |
| L1 | 4/4 | 100.0% |
| L2 | 8/9 | 88.9% |
| L3 | 6/7 | 85.7% |

按智能体分配：

| 智能体 | 承担题数 |
| --- | --- |
| 智能体 02 | 20 |

## 3. 能力进化

所有智能体初始能力值均为 0.5；每题结束后，按“所需能力维度 + 成功/失败”更新完成该题的智能体。下面是评测结束时的能力向量：

| 智能体 | 空间计算 | 属性查询 | 统计分析 | 制图可视化 | 参与题数 |
| --- | --- | --- | --- | --- | --- |
| 智能体 01 | 0.5000 | 0.5000 | 0.5000 | 0.5000 | 0 |
| 智能体 02 | 0.8048 | 0.7684 | 0.7341 | 0.5000 | 20 |
| 智能体 03 | 0.5000 | 0.5000 | 0.5000 | 0.5000 | 0 |
| 智能体 04 | 0.5000 | 0.5000 | 0.5000 | 0.5000 | 0 |

> 说明：初始阶段四个智能体完全等价，路由由随机抽取决定；随着成功/失败经验累积，能力值会分叉，后续题目逐渐由在该维度上更熟练的智能体承担。

## 4. 逐题结果

| 题号 | 等级 | 结果 | 智能体 | 工具链 | 耗时(s) |
| --- | --- | --- | --- | --- | --- |
| D01 | L1 | ✅ | 02 | query_features → query_features → query_features | 13.7 |
| D02 | L1 | ✅ | 02 | query_features → query_features → summarize_features | 8.2 |
| D03 | L1 | ✅ | 02 | query_features → query_features | 7.9 |
| D04 | L1 | ✅ | 02 | query_features → summarize_features | 7.5 |
| D05 | L2 | ✅ | 02 | query_features → query_features → clip_features → measure_features → summarize_features | 12.6 |
| D06 | L2 | ✅ | 02 | query_features → query_features → clip_features → measure_features | 11.2 |
| D07 | L2 | ✅ | 02 | query_features → query_features → clip_features → measure_features | 10.2 |
| D08 | L2 | ✅ | 02 | query_features → query_features → buffer_geometry → intersection_geometry → measure_geometry | 10.5 |
| D09 | L2 | ✅ | 02 | query_features → query_features → buffer_geometry → intersection_geometry → measure_geometry | 11.9 |
| D10 | L2 | ✅ | 02 | query_features → intersection_geometry → measure_geometry | 9.2 |
| D11 | L2 | ✅ | 02 | query_features → query_features → intersection_geometry → measure_geometry | 10.0 |
| D12 | L2 | ✅ | 02 | query_features → query_features → query_features → measure_features | 10.8 |
| D13 | L3 | ✅ | 02 | query_features → query_features → query_features → buffer_features → union_features → clip_features(失败) → intersection_geometry → measure_geometry → measure_geometry → calculate_ratio | 17.0 |
| D14 | L2 | ❌ | 02 | query_features → query_features → query_features → clip_features → buffer_features → union_features → clip_features → clip_features → measure_features → summarize_features | 19.0 |
| D15 | L3 | ✅ | 02 | query_features → query_features → query_features → buffer_features → measure_features → union_features → measure_geometry | 13.2 |
| D16 | L3 | ✅ | 02 | query_features → measure_features → union_features → intersection_geometry → measure_geometry → measure_geometry | 12.5 |
| D17 | L3 | ✅ | 02 | query_features → query_features → query_features → buffer_features → union_features → clip_features(失败) → intersection_geometry → measure_geometry → query_features → clip_features → measure_features | 18.9 |
| D18 | L3 | ✅ | 02 | query_features → query_features → query_features → clip_features → clip_features → measure_features → measure_features → summarize_features → summarize_features | 14.2 |
| D19 | L3 | ✅ | 02 | query_features → query_features → query_features → query_features → union_features → union_features → query_features → query_features → summarize_features → summarize_features → intersection_geometry → query_features → query_features | 17.7 |
| D20 | L3 | ❌ | 02 | query_features → query_features → query_features → clip_features → buffer_features → union_features → query_features → query_features → clip_features → clip_features → measure_features → summarize_features → summarize_features → summarize_features | 22.3 |

## 5. 逐题详情与差异

### D01（L1）✅ 通过

**题目**：统计严格位于施工区 A001 内、状态为正常的燃气设备数量，边界上的设备不计入。

**期望**：```json
{
  "count": 2
}
```

**实际**：```json
{
  "count": 2
}
```

**工具调用**：query_features（共 3 步）

### D02（L1）✅ 通过

**题目**：统计与施工区 A001 相交、状态为正常或告警的燃气设备数量，包含边界设备，同一设备只计一次。

**期望**：```json
{
  "count": 4
}
```

**实际**：```json
{
  "count": 4
}
```

**工具调用**：query_features，summarize_features（共 3 步）

### D03（L1）✅ 通过

**题目**：统计与含孔洞的施工区 A003 相交、状态为正常的燃气设备数量，孔洞内的设备不计入，边界接触计入。

**期望**：```json
{
  "count": 1
}
```

**实际**：```json
{
  "count": 1
}
```

**工具调用**：query_features（共 2 步）

### D04（L1）✅ 通过

**题目**：查询全部状态为正常的燃气设备，按 device_type 分组计数，按设备类型名称升序输出全部分组。

**期望**：```json
{
  "unit": "feature",
  "groups": [
    {
      "group": {
        "device_type": "监测点"
      },
      "value": 1,
      "feature_count": 1
    },
    {
      "group": {
        "device_type": "调压站"
      },
      "value": 2,
      "feature_count": 2
    },
    {
      "group": {
        "device_type": "阀门"
      },
      "value": 7,
      "feature_count": 7
    }
  ]
}
```

**实际**：```json
{
  "unit": "feature",
  "groups": [
    {
      "group": {
        "device_type": "监测点"
      },
      "value": 1.0,
      "feature_count": 1.0
    },
    {
      "group": {
        "device_type": "调压站"
      },
      "value": 2.0,
      "feature_count": 2.0
    },
    {
      "group": {
        "device_type": "阀门"
      },
      "value": 7.0,
      "feature_count": 7.0
    }
  ]
}
```

**工具调用**：query_features，summarize_features（共 2 步）

### D05（L2）✅ 通过

**题目**：将所有与 A001 相交的燃气管线裁剪到 A001，按 pressure_level 汇总区内长度（米），按总长度降序、同长按压力名称升序，输出全部分组。边界上的线段计入。

**期望**：```json
{
  "unit": "meter",
  "groups": [
    {
      "group": {
        "pressure_level": "高压"
      },
      "value": 2414.213562373095,
      "feature_count": 2
    },
    {
      "group": {
        "pressure_level": "中压"
      },
      "value": 2400,
      "feature_count": 3
    },
    {
      "group": {
        "pressure_level": "低压"
      },
      "value": 1000,
      "feature_count": 1
    }
  ]
}
```

**实际**：```json
{
  "unit": "meter",
  "groups": [
    {
      "group": {
        "pressure_level": "高压"
      },
      "value": 2414.213562373095,
      "feature_count": 2
    },
    {
      "group": {
        "pressure_level": "中压"
      },
      "value": 2400.0,
      "feature_count": 3
    },
    {
      "group": {
        "pressure_level": "低压"
      },
      "value": 1000.0,
      "feature_count": 1
    }
  ]
}
```

**工具调用**：query_features，clip_features，measure_features，summarize_features（共 5 步）

### D06（L2）✅ 通过

**题目**：计算燃气管线 G006 位于施工区 A003 实体部分内的长度（米），排除孔洞，并返回参与量测的原管线数量。

**期望**：```json
{
  "length": {
    "unit": "meter",
    "value": 600,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 1
  }
}
```

**实际**：```json
{
  "length": {
    "unit": "meter",
    "value": 600.0,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 1
  }
}
```

**工具调用**：query_features，clip_features，measure_features（共 4 步）

### D07（L2）✅ 通过

**题目**：计算所有水管位于施工区 A003 实体部分内的总长度（米），排除孔洞，包含边界接触，并返回非空裁剪结果的源水管数量。

**期望**：```json
{
  "length": {
    "unit": "meter",
    "value": 700,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 3
  }
}
```

**实际**：```json
{
  "length": {
    "unit": "meter",
    "value": 700.0,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 3
  }
}
```

**工具调用**：query_features，clip_features，measure_features（共 4 步）

### D08（L2）✅ 通过

**题目**：以燃气设备 D011 为中心建立 300 米缓冲区，计算缓冲区位于 A001 内的面积（平方米）。

**期望**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 280930.06370322476,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**实际**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 280930.06370322476,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**工具调用**：query_features，buffer_geometry，intersection_geometry，measure_geometry（共 5 步）

### D09（L2）✅ 通过

**题目**：以燃气设备 D011 为中心建立 700 米缓冲区，计算缓冲区位于 A001 内的面积（平方米）。

**期望**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 998412.9907871715,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**实际**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 998412.9907871715,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**工具调用**：query_features，buffer_geometry，intersection_geometry，measure_geometry（共 5 步）

### D10（L2）✅ 通过

**题目**：计算施工区 A001 与 A002 交集的长度（米）；两区仅共边时，返回公共边界长度而不是面积。

**期望**：```json
{
  "length": {
    "unit": "meter",
    "value": 1000,
    "measure": "length",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**实际**：```json
{
  "length": {
    "unit": "meter",
    "value": 1000.0,
    "measure": "length",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**工具调用**：query_features，intersection_geometry，measure_geometry（共 3 步）

### D11（L2）✅ 通过

**题目**：计算施工区 A001 与狭长施工区 A008 的重叠面积（平方米）。

**期望**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 140000,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**实际**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 140000.0,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**工具调用**：query_features，intersection_geometry，measure_geometry（共 4 步）

### D12（L2）✅ 通过

**题目**：计算所有水管位于孤立施工区 A009 内的总长度（米），并返回非空裁剪结果的源水管数量。若没有匹配水管，长度和数量都返回 0，不报目标不存在。

**期望**：```json
{
  "length": {
    "unit": "meter",
    "value": 0,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 0
  }
}
```

**实际**：```json
{
  "length": {
    "unit": "meter",
    "value": 0.0,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 0
  }
}
```

**工具调用**：query_features，measure_features（共 4 步）

### D13（L3）✅ 通过

**题目**：对与 A001 相交且正常或告警的燃气设备分别建立 300 米缓冲区，合并重叠后裁剪到 A001，求覆盖面积（平方米）以及占 A001 面积的百分比。边界设备计入。

**期望**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 639185.4490710819,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  },
  "coverage_percent": {
    "unit": "percent",
    "value": 63.9185449071082,
    "numerator": 639185.4490710819,
    "denominator": 1000000
  }
}
```

**实际**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 639185.449071082,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  },
  "coverage_percent": {
    "unit": "percent",
    "value": 63.91854490710821,
    "numerator": 639185.449071082,
    "denominator": 1000000.0
  }
}
```

**工具调用**：query_features，buffer_features，union_features，intersection_geometry，measure_geometry，calculate_ratio（共 10 步）

### D14（L2）❌ 未通过

**题目**：取与 A001 相交的高压燃气管线，先裁剪到 A001，再分别缓冲 50 米并合并。计算各水管在该影响范围且在 A001 内的长度（米），按长度降序、同长按水管编码升序输出全部水管及总长度。保留非空的零长度边界接触记录。

**期望**：```json
{
  "unit": "meter",
  "groups": [
    {
      "group": {
        "source_code": "W001"
      },
      "value": 1000,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W008"
      },
      "value": 220.71067811865476,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W009"
      },
      "value": 0,
      "feature_count": 1
    }
  ],
  "total_length": {
    "unit": "meter",
    "value": 1220.7106781186549,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 3
  }
}
```

**实际**：```json
{
  "unit": "meter",
  "groups": [
    {
      "group": {
        "source_code": "W001"
      },
      "value": 1000.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W008"
      },
      "value": 220.71067811865476,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W002"
      },
      "value": 0.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W003"
      },
      "value": 0.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W004"
      },
      "value": 0.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W005"
      },
      "value": 0.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W006"
      },
      "value": 0.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W007"
      },
      "value": 0.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W009"
      },
      "value": 0.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W010"
      },
      "value": 0.0,
      "feature_count": 1
    }
  ],
  "total_length": {
    "unit": "meter",
    "value": 1220.7106781186549,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 10
  }
}
```

**差异**：$.groups: 长度 10，期望 3；$.total_length.feature_count: 10，期望 3

**工具调用**：query_features，clip_features，buffer_features，union_features，measure_features，summarize_features（共 10 步）

**反馈**：$.groups: 长度 10，期望 3；$.total_length.feature_count: 10，期望 3

### D15（L3）✅ 通过

**题目**：对与 A001 相交且状态正常的设备分别缓冲 200 米，不裁剪缓冲区。分别给出所有缓冲面积直接相加的结果，以及缓冲合并去重后的面积（平方米），复用同一批缓冲结果。

**期望**：```json
{
  "union_area": {
    "unit": "square_meter",
    "value": 370190.3751365281,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  },
  "summed_area": {
    "unit": "square_meter",
    "value": 374573.4182709662,
    "measure": "area",
    "measure_srid": 3857,
    "feature_count": 3
  }
}
```

**实际**：```json
{
  "summed_area": {
    "unit": "square_meter",
    "value": 374573.4182709662,
    "measure": "area",
    "measure_srid": 3857,
    "feature_count": 3
  },
  "union_area": {
    "unit": "square_meter",
    "value": 370190.3751365281,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**工具调用**：query_features，buffer_features，measure_features，union_features，measure_geometry（共 7 步）

### D16（L3）✅ 通过

**题目**：针对 A001 和 A008，分别计算两区面积直接相加、联合覆盖去重面积和重叠面积（平方米），不要将三者混淆。联合覆盖与直接相加应复用同一份区域查询结果。

**期望**：```json
{
  "union_area": {
    "unit": "square_meter",
    "value": 1100000,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  },
  "summed_area": {
    "unit": "square_meter",
    "value": 1240000,
    "measure": "area",
    "measure_srid": 3857,
    "feature_count": 2
  },
  "overlap_area": {
    "unit": "square_meter",
    "value": 140000,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**实际**：```json
{
  "summed_area": {
    "unit": "square_meter",
    "value": 1240000.0,
    "measure": "area",
    "measure_srid": 3857,
    "feature_count": 2
  },
  "union_area": {
    "unit": "square_meter",
    "value": 1100000.0,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  },
  "overlap_area": {
    "unit": "square_meter",
    "value": 140000.0,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  }
}
```

**工具调用**：query_features，measure_features，union_features，intersection_geometry，measure_geometry（共 6 步）

### D17（L3）✅ 通过

**题目**：与 A001 相交且正常或告警的设备分别缓冲 300 米，合并后裁剪到 A001。复用该覆盖几何，分别计算覆盖面积（平方米）和其中全部燃气管线的总长度（米），保留非空零长度接触记录。

**期望**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 639185.4490710819,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  },
  "gas_length": {
    "unit": "meter",
    "value": 4332.362443880318,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 6
  }
}
```

**实际**：```json
{
  "area": {
    "unit": "square_meter",
    "value": 639185.449071082,
    "measure": "area",
    "is_empty": false,
    "measure_srid": 3857
  },
  "gas_length": {
    "unit": "meter",
    "value": 4332.362443880317,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 6
  }
}
```

**工具调用**：query_features，buffer_features，union_features，intersection_geometry，measure_geometry，clip_features，measure_features（共 11 步）

### D18（L3）✅ 通过

**题目**：在 A001 内分别统计两类数据：燃气管线按 pressure_level 分组汇总裁剪后长度，水管按 pipe_type 分组汇总裁剪后长度，单位均为米。每类按总长度降序、同长按分组名称升序，输出全部分组，保留零长度非空接触记录。

**期望**：```json
{
  "unit": "meter",
  "gas_groups": [
    {
      "group": {
        "pressure_level": "高压"
      },
      "value": 2414.213562373095,
      "feature_count": 2
    },
    {
      "group": {
        "pressure_level": "中压"
      },
      "value": 2400,
      "feature_count": 3
    },
    {
      "group": {
        "pressure_level": "低压"
      },
      "value": 1000,
      "feature_count": 1
    }
  ],
  "water_groups": [
    {
      "group": {
        "pipe_type": "给水"
      },
      "value": 1700,
      "feature_count": 3
    }
  ]
}
```

**实际**：```json
{
  "unit": "meter",
  "gas_groups": [
    {
      "group": {
        "pressure_level": "高压"
      },
      "value": 2414.213562373095,
      "feature_count": 2
    },
    {
      "group": {
        "pressure_level": "中压"
      },
      "value": 2400.0,
      "feature_count": 3
    },
    {
      "group": {
        "pressure_level": "低压"
      },
      "value": 1000.0,
      "feature_count": 1
    }
  ],
  "water_groups": [
    {
      "group": {
        "pipe_type": "给水"
      },
      "value": 1700.0,
      "feature_count": 3
    }
  ]
}
```

**工具调用**：query_features，clip_features，measure_features，summarize_features（共 9 步）

### D19（L3）✅ 通过

**题目**：分别统计与 A001、A002 相交且状态正常的设备数，再将两个施工区合并后统计正常设备的联合去重数量。边界设备计入各区，但联合统计中同一个设备只计一次，不能直接把两区数量相加。

**期望**：```json
{
  "a001_count": 3,
  "a002_count": 3,
  "unique_count": 5
}
```

**实际**：```json
{
  "a001_count": 3,
  "a002_count": 3,
  "unique_count": 5
}
```

**工具调用**：query_features，union_features，summarize_features，intersection_geometry（共 13 步）

### D20（L3）❌ 未通过

**题目**：取与 A001 相交的高压燃气管线，先裁剪到 A001，再分别缓冲 50 米合并为同一影响范围。复用该范围：（1）统计 A001 内正常或告警设备，按状态升序分组计数；（2）计算 A001 内各水管受影响长度（米），按长度降序、同长按编码升序，并给出总长度。边界计入，水管非空零长度接触记录保留。

**期望**：```json
{
  "water_unit": "meter",
  "device_unit": "feature",
  "total_length": {
    "unit": "meter",
    "value": 1220.7106781186549,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 3
  },
  "water_groups": [
    {
      "group": {
        "source_code": "W001"
      },
      "value": 1000,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W008"
      },
      "value": 220.71067811865476,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W009"
      },
      "value": 0,
      "feature_count": 1
    }
  ],
  "device_groups": [
    {
      "group": {
        "status": "告警"
      },
      "value": 1,
      "feature_count": 1
    },
    {
      "group": {
        "status": "正常"
      },
      "value": 2,
      "feature_count": 2
    }
  ]
}
```

**实际**：```json
{
  "water_unit": "meter",
  "device_unit": "feature",
  "total_length": {
    "unit": "meter",
    "value": 1220.7106781186549,
    "measure": "length",
    "measure_srid": 3857,
    "feature_count": 3
  },
  "water_groups": [
    {
      "group": {
        "source_code": "W001"
      },
      "value": 1000.0,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W008"
      },
      "value": 220.71067811865476,
      "feature_count": 1
    },
    {
      "group": {
        "source_code": "W009"
      },
      "value": 0.0,
      "feature_count": 1
    }
  ],
  "device_groups": [
    {
      "group": {
        "status": "告警"
      },
      "value": 1.0,
      "feature_count": 1
    },
    {
      "group": {
        "status": "正常"
      },
      "value": 3.0,
      "feature_count": 3
    }
  ]
}
```

**差异**：$.device_groups[1].value: 3，期望 2；$.device_groups[1].feature_count: 3，期望 2

**工具调用**：query_features，clip_features，buffer_features，union_features，measure_features，summarize_features（共 14 步）

**反馈**：$.device_groups[1].value: 3，期望 2；$.device_groups[1].feature_count: 3，期望 2

## 6. 评测过程与环境说明

- **环境自检**：先用 Debian 版 `postgis/postgis:16-3.4` 镜像（GEOS 3.9.0）时发现“线完全落在面内”会让 `ST_Intersection` 返回空，裁剪类题目全部失真；换用 alpine 镜像（GEOS 3.12.2）后恢复正常。正式评测基于 alpine 镜像。
- **迭代过程**：首轮 16/20，补充“单几何/要素集工具不可混用、不要滥用 keep_empty、多范围条件要依次裁剪”等通用执行约束后为 17/20，再补充裁剪语义与空几何说明后为 18/20。所有约束都是任务无关的工具使用规则，没有向模型提供题目答案或参考计划。
- **判分方式**：用题集自带的标准答案快照做确定性比较（数值容差 1e-6，列表按题目要求顺序比较），不依赖 LLM 判卷。

## 7. 结论与局限

- 本次在真实 PostGIS 数据上完成 20 题，正确 18 题（90.0%），平均 12.9 秒/题。
- 空间计算本身由 PostGIS 完成，正确性取决于：工具选择、空间关系语义（ST_Within / ST_Intersects）、是否先裁剪后量测、分组与排序规则、以及是否复用中间结果。
- 评测使用单次作答（不重规划），失败题会作为失败经验写入能力向量与经验池；重规划能力由 `MAX_REPLANS` 控制，可在完整运行中开启。
- dev20 是开发题集，题目和标准答案均为已知，不代表正式泛化成绩。

## 8. 复现方式

```powershell
# 1) 启动并导入数据（见第 1 节）
# 2) 配置 Test/.env：DATABASE_URL、LLM_MODEL、POSTGIS_TOOLKIT_ROOT
# 3) 跑评测
python scripts/run_dev20_benchmark.py
```
