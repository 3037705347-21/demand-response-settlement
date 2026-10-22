# 商业需求响应结算复核

区域聚合商每月向商业用户支付削峰补偿。现在 `dr_settle` 只按本地时间表面做差，遇到秋季回拨时会把重复的一小时合并，基线候选日里的维护和缺测记录也没有剔掉，财务复核经常对不上。请修复 `/workspace/dr_settle`，保持下面的入口：

```bash
python -m dr_settle --input-dir data --output-dir out
```

## 输入文件

`events.csv` 的列固定为 `event_id,site_id,start_local,end_local,timezone,committed_kw,rate_usd_per_kwh`。两个本地时间不带偏移，必须落在整刻钟边界，结束晚于开始；时区使用系统可识别的 IANA 名称。`committed_kw` 为正，`rate_usd_per_kwh` 非负。

`baseline_days.csv` 的列固定为 `date,status`。`status` 只能是 `normal`、`maintenance`、`incomplete` 或 `event`，日期不能重复。

`readings.csv` 的列固定为 `site_id,timestamp_utc,kwh`。时间戳必须是带 `Z` 的 UTC 时间并落在 15 分钟边界，同一 `site_id` 下的同一时间戳只能出现一次；`kwh` 是该站点在 15 分钟内的电量，必须为非负有限数。平均功率按 `kwh * 4` 换算。

`portfolio.csv` 只有一行，列固定为 `target_mwh,budget_usd,max_events,demand_charge_usd_per_kw`。前三个字段中 `target_mwh` 和 `budget_usd` 为非负有限数，`max_events` 为非负整数；`demand_charge_usd_per_kw` 非负。候选事件最多 32 条，单次结算应在测试环境的 30 秒内完成。

## 事件区间

先把事件起止本地时间按事件时区解析为 UTC，再按 UTC 实际经过时间每 15 分钟展开，直到结束时间但不包含结束点，最后把每个区间起点转回本地时间。这样秋季回拨时同一个墙上时刻会出现两次并保留各自的 UTC 偏移；春季跳时后不存在的墙上时刻不会生成。事件边界本身落在回拨重复小时时，`start_local` 取较早发生的实例，`end_local` 取较晚发生的实例；任一边界落在春季不存在的墙上时间时整次失败。`local_start` 使用带偏移的 ISO 8601，`start_utc` 使用以 `Z` 结尾的 ISO 8601。

## 负荷基线

对事件每个区间的墙上 `HH:MM` 分别计算基线。候选日只取事件本地日期之前、状态为 `normal`，且具备事件全部不同墙上时刻读数的日期。某日只要缺一个所需时刻，整天都不能进入候选。按该墙上时刻的功率从高到低取前 5 天求平均；不足 5 天时整次结算失败。回拨日重复出现的两个同名墙上时刻共用这个基线。

事件区间内的 `actual_kw` 按 `site_id` 和 `start_utc` 精确匹配读数，不得用本地墙上时间代替 UTC。基线同样按事件的 `site_id` 取该站点的候选日读数。每个区间的削减为 `max(0, baseline_kw - actual_kw)`，计费削减再受事件 `committed_kw` 限制。区间补偿为 `eligible_reduction_kw * 0.25 * rate_usd_per_kwh`。

## 产物

成功后输出 `out/settlement.json` 和 `out/summary.csv`。JSON 顶层为 `currency`（固定 `USD`）和 `events`。每个事件依次包含：

```text
event_id, site_id, timezone, committed_kw, rate_usd_per_kwh, intervals, totals
```

`intervals` 每项字段固定为：

```text
local_start, start_utc, baseline_kw, actual_kw, reduction_kw,
eligible_reduction_kw, payment_usd
```

`totals` 包含 `reduction_kwh`、`eligible_kwh`、`payment_usd`。两张产物中的数值均保留 3 位小数；总量必须由未提前舍入的区间结果求和后再取整。`summary.csv` 表头固定为 `event_id,site_id,reduction_kwh,eligible_kwh,payment_usd`，事件顺序与输入一致。

同一站点两个候选事件的 UTC 区间只要有任意一个 15 分钟块重叠，就不能同时入选。选出的组合必须满足 `max_events`。组合的区间补偿是各事件 `payment_usd` 之和；同一 UTC 区间块内所有已选事件的 `committed_kw` 相加，整个组合取这个和的最大值作为同刻峰值，再乘 `demand_charge_usd_per_kw` 得到需量电费。区间补偿加需量电费不得超过 `budget_usd`，且总 `eligible_kwh` 不低于 `target_mwh * 1000`。先最小化总成本；总成本相同时最大化合格电量；两者仍相同，按事件 ID 排序后的序列取字典序最小者。

另输出 `out/portfolio.json`，字段为 `selected_event_ids`、`eligible_kwh`、`incentive_usd`、`demand_charge_usd`、`payment_usd`。`payment_usd` 是区间补偿与需量电费之和。事件 ID 按字符串升序排列，电量和金额与 `settlement.json` 中同一事件的总量一致并保留 3 位小数。

任何字段、时间边界、唯一性、状态或候选数量不合格，或者不存在满足目标的组合，都应返回非零状态，并且不得新建或覆盖三份正式产物。`data/` 是按固定种子生成的复核样例，不是现场采集数据。
