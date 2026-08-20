# 结构化因子数据获取命令

本文件列出评估结构化因子（公司资本操作/筹码/资金/业绩动能/估值）与尾部风险熔断项所需的 WeStock CLI 与 NeoData 命令。

**WeStock CLI 基础命令格式**：
```bash
npx -y westock-data-clawhub@1.0.4 <command> <code> [options]
```

**市场代码前缀**：
- A 股：`sh`（沪）、`sz`（深）、`bj`（北交所）
- 港股：`hk`
- 美股：`us`

---

## 0. 标的解析与公司简况

```bash
# 搜索股票（不支持批量）
npx -y westock-data-clawhub@1.0.4 search 比亚迪

# 公司简况（行业、主营、上市日期、董事长等）
npx -y westock-data-clawhub@1.0.4 profile sh002594
npx -y westock-data-clawhub@1.0.4 profile hk01211
```

---

## 1. 公司资本操作（因子 10）

```bash
# 股东结构：A股看十大股东/十大流通股东/股东户数；港股看持股股东+机构持仓
npx -y westock-data-clawhub@1.0.4 shareholder sh002594
npx -y westock-data-clawhub@1.0.4 shareholder hk01211

# 业绩预告（辅助判断公司经营动向）
npx -y westock-data-clawhub@1.0.4 reserve sh002594

# 分红数据（回购/分红回馈股东）
npx -y westock-data-clawhub@1.0.4 dividend sh002594 --years 3
```

**增持/减持/回购公告**：WeStock 无直接命令，用元宝搜索标准版查"公司名 增持/减持/回购 公告"，优先 T0（交易所公告）。

---

## 2. 筹码多空（因子 11）

```bash
# 筹码成本分布（仅沪深京A股，港股不支持）
npx -y westock-data-clawhub@1.0.4 chip sh002594
npx -y westock-data-clawhub@1.0.4 chip sh002594 --start 2026-01-01 --end 2026-07-09

# 股东户数变化（户数减少=筹码集中）
npx -y westock-data-clawhub@1.0.4 shareholder sh002594
```

**港股筹码**：WeStock 不支持，用 `shareholder hk01211` 看机构持仓，或元宝搜索"公司名 机构持仓变化 筹码集中度"。

**判定要点**：
- 获利盘比例：>70% 偏多，<30% 偏空（高位时）。
- 平均成本 vs 现价：现价高于平均成本且无高位密集峰=筹码健康。
- 高位套牢盘：若现价下方有大量筹码堆积=套牢盘轻；若现价上方有大量筹码=套牢盘重。

---

## 3. 资金多空（因子 12）

### A 股

```bash
# 融资融券（仅沪深，看融资余额/融券余额历史分位）
npx -y westock-data-clawhub@1.0.4 margintrade sz000001

# A股资金流向（主力/超大单/大单净流入）
npx -y westock-data-clawhub@1.0.4 asfund sh600000
npx -y westock-data-clawhub@1.0.4 asfund sh600000 --date 2026-07-09

# 龙虎榜（仅沪深，看机构/游资动向）
npx -y westock-data-clawhub@1.0.4 lhb sz000001

# 大宗交易（仅沪深）
npx -y westock-data-clawhub@1.0.4 blocktrade sz000001
```

### 港股

```bash
# 港股资金流向
npx -y westock-data-clawhub@1.0.4 hkfund hk01211
npx -y westock-data-clawhub@1.0.4 hkfund hk01211 --date 2026-07-09
```

### 北向资金（A 股）

- 若 `westock-mcp` 连接器已连接：用 `data_north_holding` 工具查询北向资金持股。
- 若未连接：元宝搜索"公司名 北向资金 持股 变化"。

### 港股 call/put

WeStock 无直接命令，元宝搜索"公司名 衍生品 call put 未平仓合约"或"公司名 牛熊证 街货"。

**判定要点**：
- 融资余额：近 1 年分位 <30% 偏多（低位），>70% 偏空（高位）。
- 融券余额：高位偏空（做空压力大），低位偏多。
- 主力资金：持续净流入偏多，持续净流出偏空。
- 北向资金：持续增持偏多，持续减持偏空。

---

## 4. 业绩动能（因子 13）

```bash
# 利润表（8+ 季度，取单季营收/归母NP/扣非NP/资产减值等）
npx -y westock-data-clawhub@1.0.4 finance sh002594 --type lrb --num 8

# 资产负债表（存货/应收/合同负债/流动比率/净资产等）
npx -y westock-data-clawhub@1.0.4 finance sh002594 --type zcfz --num 8

# 现金流量表（经营现金流）
npx -y westock-data-clawhub@1.0.4 finance sh002594 --type xjll --num 8
```

**自动化脚本（推荐）**：

```bash
python3 scripts/momentum_calc.py sh002594
```

脚本自动获取三大报表、计算 14 项检查指标、检测趋势、输出预警报告（检查项定义见 [momentum-check.md](./momentum-check.md)），仅依赖 Python 标准库。港股 `finance` 不支持时按 momentum-check.md「港股特殊处理」执行。

**13a 预期差校验**：卖方一致预期用 NeoData 金融搜索获取（见第 8 节），对比规则见 factor-definitions.md 第 13a 节。

---

## 5. 尾部风险熔断取数（SKILL.md 第 1.6 步）

| 熔断项 | 取数方式 |
|--------|----------|
| 偿债红线 | 复用因子 13 已取的资产负债表/现金流量表（货币资金/短期借款/流动比率/经营现金流）；利息收入查利润表财务费用明细或年报附注 |
| 审计与治理红线 | 元宝搜索"公司名 审计意见 年报""公司名 更换会计师事务所""公司名 立案调查"，优先 T0（年报原文/交易所公告/证监会公告） |
| 大股东质押红线 | 元宝搜索"公司名 控股股东 质押 比例 平仓线"，优先 T0（交易所质押公告/中国结算数据） |
| 客户集中度红线 | 最新年报"前五名客户销售额"章节（T0），元宝搜索"公司名 第一大客户 占比 年报" |

所有熔断证据须标注数据日期与信源级别，T0 优先。

---

## 6. 估值（因子 14）

先按 SKILL.md 纪律第 23 条判定公司类型（成长/价值/周期），再取对应主指标（成长→PEG/PS，价值→PE/股息率，周期→PB）。

### 方法 1：元宝搜索（优先，T2+ 来源）

```
公司名 PE/PB 历史分位 5年（理杏仁/乐咕乐股/券商研报）
公司名 PEG 一致预期增速
行业 可比公司 估值对比
```

### 方法 2：NeoData 金融搜索

调用 `neodata-financial-search` skill：
```
公司名 估值分位 PE PB
公司名 一致预期 净利润增速（与 13a 共用）
```

### 方法 3：手动计算（数据源均无时，周期股 PB 分位适用）

```bash
# 取近5年（20季）资产负债表，拿净资产
npx -y westock-data-clawhub@1.0.4 finance sh002594 --type zcfzb --num 20

# 取近5年周K（约260周），拿收盘价
npx -y westock-data-clawhub@1.0.4 kline sh002594 --period week --limit 260
```

计算步骤：
1. 从资产负债表取每季度"归属母公司股东权益合计"。
2. 从 K 线取对应日期收盘价 × 总股本 = 总市值。
3. PB = 总市值 / 归母净资产。
4. 构建近 5 年 PB 序列，求当前 PB 在序列中的百分位。

**分位判定**：<10% 利多 / 10%-30% 中性偏多 / 30%-70% 中性 / 70%-90% 中性偏空 / >90% 利空（成长股改用 PEG 档位，见 factor-definitions.md 第 14 节）。

---

## 7. 技术指标辅助（可选）

```bash
# 全部技术指标（均线/MACD/KDJ/RSI/BOLL等）
npx -y westock-data-clawhub@1.0.4 technical sh002594 --group all

# K线（看趋势/支撑压力位）
npx -y westock-data-clawhub@1.0.4 kline sh002594 --period day --limit 60
```

技术指标不直接对应 14 因子，但可辅助判断筹码/资金因子的多空倾向（如均线多头排列支撑"资金偏多"判断）。

---

## 8. NeoData 金融搜索（机构观点与一致预期）

调用 `neodata-financial-search` skill，适合查询：
- 机构评级与目标价（机构观点一致性）
- 券商研报（竞争格局/行业景气度/壁垒分析）
- 机构持仓全景（辅助筹码判断）
- 卖方一致预期净利润/营收增速（因子 13a 预期差校验与因子 14 PEG 增速共用）

示例查询：
```
比亚迪 机构评级 目标价
比亚迪 研报 竞争格局
比亚迪 一致预期 净利润增速
腾讯 机构持仓
```

---

## 数据获取顺序建议

1. 先并行跑：`search` → `profile`（解析标的）。
2. 标的确认后并行跑：`chip`（A股）、`margintrade`（A股）、`asfund`/`hkfund`、`shareholder`、`finance`（业绩动能/熔断用）、`kline`（估值用）。
3. 同时用元宝搜索查定性因子（宏观/政策/行业/上下游/竞争对手/替代品）与估值分位。
4. 用 NeoData 补充机构观点、研报与一致预期。
5. 利空因子定下跟踪指标后，逐个用元宝搜索查进展。
