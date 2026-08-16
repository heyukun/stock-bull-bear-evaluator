# 结构化因子数据获取命令

本文件列出评估结构化因子（公司资本操作/筹码/资金/估值）所需的 WeStock CLI 与 NeoData 命令。

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

## 4. 估值水位（因子 13）

### 方法 1：NeoData 金融搜索（优先）

调用 `neodata-financial-search` skill，查询：
```
公司名 PB 估值分位 历史百分位
公司名 PE 估值分位
```

### 方法 2：元宝搜索（次选）

```
公司名 PB 历史分位 5年
公司名 估值 百分位
```

### 方法 3：手动计算（数据源均无时）

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

**判定**：
- 分位 <10%：利多（深度低估）。
- 分位 10%-30%：中性偏多。
- 分位 30%-70%：中性。
- 分位 70%-90%：中性偏空。
- 分位 >90%：利空（严重高估）。

---

## 5. 技术指标辅助（可选）

```bash
# 全部技术指标（均线/MACD/KDJ/RSI/BOLL等）
npx -y westock-data-clawhub@1.0.4 technical sh002594 --group all

# K线（看趋势/支撑压力位）
npx -y westock-data-clawhub@1.0.4 kline sh002594 --period day --limit 60
```

技术指标不直接对应 13 因子，但可辅助判断筹码/资金因子的多空倾向（如均线多头排列支撑"资金偏多"判断）。

---

## 6. NeoData 金融搜索（机构观点补充）

调用 `neodata-financial-search` skill，适合查询：
- 机构评级与目标价（机构观点一致性）
- 券商研报（竞争格局/行业景气度/壁垒分析）
- 机构持仓全景（辅助筹码判断）

示例查询：
```
比亚迪 机构评级 目标价
比亚迪 研报 竞争格局
腾讯 机构持仓
```

---

## 数据获取顺序建议

1. 先并行跑：`search` → `profile`（解析标的）。
2. 标的确认后并行跑：`chip`（A股）、`margintrade`（A股）、`asfund`/`hkfund`、`shareholder`、`finance`（估值用）、`kline`（估值用）。
3. 同时用元宝搜索查定性因子（宏观/政策/行业/上下游/竞争对手/替代品）。
4. 用 NeoData 补充机构观点与研报。
5. 利空因子定下跟踪指标后，逐个用元宝搜索查进展。
