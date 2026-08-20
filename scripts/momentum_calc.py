#!/usr/bin/env python3
"""
业绩动能（因子 13）检查计算脚本

从 WeStock CLI 获取最近 8+ 个季度财务数据，计算营收/利润/现金流趋势
和财务比率（周转率/流动性）趋势，输出预警报告。

仅依赖 Python 标准库。

Usage:
    python3 momentum_calc.py <stock_code> [num_quarters]

Example:
    python3 momentum_calc.py sh688508
    python3 momentum_calc.py sh688508 12
"""

import subprocess
import sys
import re
from datetime import datetime


# ============================================================
# 数据获取
# ============================================================

def fetch_finance_data(stock_code, stmt_type, num=8):
    """通过 WeStock CLI 获取财务报表数据"""
    cmd = [
        'npx', '-y', 'westock-data-clawhub@1.0.4',
        'finance', stock_code,
        '--type', stmt_type,
        '--num', str(num)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.stdout


# ============================================================
# 表格解析
# ============================================================

def parse_markdown_table(md_text):
    """解析 markdown pipe 表格为 dict 列表，按日期升序排列"""
    lines = md_text.strip().split('\n')
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('|') and '---' not in stripped and '_date' in stripped:
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = [h.strip() for h in lines[header_idx].split('|') if h.strip()]

    rows = []
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        values = [v.strip() for v in line.split('|') if v.strip()]
        if len(values) >= len(headers):
            row = dict(zip(headers, values))
            rows.append(row)

    rows.sort(key=lambda r: r.get('_date', ''))
    return rows


def to_float(val):
    """安全转换字符串为浮点数"""
    if val is None or val == '' or val == '-' or val == 'None':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ============================================================
# 季度值计算
# ============================================================

def get_quarter(date_str):
    """从日期字符串提取季度编号 (1-4)"""
    month = int(date_str.split('-')[1])
    return (month - 1) // 3 + 1


def compute_quarterly_from_cumulative(values, dates):
    """
    从累计 (YTD) 值计算单季度值
    Q1 = 直接值; Q2 = H1 - Q1; Q3 = 9M - H1; Q4 = FY - 9M
    """
    quarterly = []
    for i, (val, date) in enumerate(zip(values, dates)):
        if val is None:
            quarterly.append(None)
            continue
        q = get_quarter(date)
        if q == 1:
            quarterly.append(val)
        elif i > 0 and values[i - 1] is not None:
            quarterly.append(val - values[i - 1])
        else:
            quarterly.append(None)
    return quarterly


# ============================================================
# YoY 增长率
# ============================================================

def compute_yoy_series(quarterly_values):
    """
    计算每个季度的 YoY 增长率（需要至少 5 个季度数据）
    返回与输入等长的列表，前 4 个为 None
    """
    yoy = []
    for i, val in enumerate(quarterly_values):
        if i < 4 or val is None:
            yoy.append(None)
            continue
        prev = quarterly_values[i - 4]
        if prev is not None and prev != 0:
            yoy.append(round((val - prev) / abs(prev) * 100, 2))
        else:
            yoy.append(None)
    return yoy


# ============================================================
# 趋势检测
# ============================================================

def detect_trend(values, min_count=3):
    """
    检测趋势方向
    返回: 'declining' | 'improving' | 'volatile' | 'insufficient_data'
    """
    valid = [v for v in values if v is not None]
    if len(valid) < min_count:
        return 'insufficient_data'

    last_n = valid[-min_count:]
    if all(last_n[i] >= last_n[i + 1] for i in range(len(last_n) - 1)):
        return 'declining'
    elif all(last_n[i] <= last_n[i + 1] for i in range(len(last_n) - 1)):
        return 'improving'
    return 'volatile'


def count_consecutive_declining(yoy_series):
    """从末尾开始数连续下降的 YoY 季度数"""
    count = 0
    valid = [v for v in yoy_series if v is not None]
    for i in range(len(valid) - 1, 0, -1):
        if valid[i] < valid[i - 1]:
            count += 1
        else:
            break
    return count


def check_turn_negative(yoy_series):
    """检查 YoY 是否从正转负"""
    valid = [v for v in yoy_series if v is not None]
    if len(valid) < 2:
        return False
    return valid[-2] > 0 and valid[-1] < 0


def check_negative_streak(yoy_series, n=2):
    """检查 YoY 是否连续 n 个季度为负"""
    valid = [v for v in yoy_series if v is not None]
    if len(valid) < n:
        return False
    return all(v < 0 for v in valid[-n:])


# ============================================================
# 财务比率计算
# ============================================================

def compute_turnover_ratios(lrb_rows, zcfz_rows, quarters_back=4):
    """
    计算 TTM 周转率比率序列
    返回最近 quarters_back 个季度的比率数据
    """
    n = min(len(lrb_rows), len(zcfz_rows))
    if n < 5:
        return []

    results = []
    for i in range(4, n):  # 从第5个季度开始（需要前4个季度算TTM）
        date = lrb_rows[i].get('_date', '')

        # TTM 营收 = 当前累计营收 + 上年同期之后到去年的累计营收 - 上年同期累计营收
        # 简化：用 TTM 字段或手动计算
        rev_ttm = to_float(lrb_rows[i].get('OperatingRevenueTTM'))
        cogs_ttm = to_float(lrb_rows[i].get('OperatingCostTTM'))

        # 资产负债表项（期末值）
        total_assets = to_float(zcfz_rows[i].get('TotalAssets'))
        inventory = to_float(zcfz_rows[i].get('Inventories'))
        ar = to_float(zcfz_rows[i].get('BillAccReceivable'))
        current_assets = to_float(zcfz_rows[i].get('TotalCurrentAssets'))
        current_liab = to_float(zcfz_rows[i].get('TotalCurrentLiability'))

        # 上期资产负债表项（用于计算平均值）
        prev_total_assets = to_float(zcfz_rows[i - 1].get('TotalAssets')) if i > 0 else None
        prev_inventory = to_float(zcfz_rows[i - 1].get('Inventories')) if i > 0 else None
        prev_ar = to_float(zcfz_rows[i - 1].get('BillAccReceivable')) if i > 0 else None

        # 平均值
        avg_total_assets = (total_assets + prev_total_assets) / 2 if total_assets and prev_total_assets else total_assets
        avg_inventory = (inventory + prev_inventory) / 2 if inventory and prev_inventory else inventory
        avg_ar = (ar + prev_ar) / 2 if ar and prev_ar else ar

        ratios = {
            'date': date,
            'total_asset_turnover': round(rev_ttm / avg_total_assets, 4) if rev_ttm and avg_total_assets else None,
            'inventory_turnover': round(cogs_ttm / avg_inventory, 4) if cogs_ttm and avg_inventory else None,
            'ar_turnover': round(rev_ttm / avg_ar, 4) if rev_ttm and avg_ar else None,
            'current_ratio': round(current_assets / current_liab, 4) if current_assets and current_liab else None,
            'quick_ratio': round((current_assets - inventory) / current_liab, 4) if current_assets and current_liab else None,
        }

        # 周转天数（年化）
        if ratios['inventory_turnover'] and ratios['inventory_turnover'] > 0:
            ratios['inventory_days'] = round(365 / ratios['inventory_turnover'], 1)
        else:
            ratios['inventory_days'] = None
        if ratios['ar_turnover'] and ratios['ar_turnover'] > 0:
            ratios['ar_days'] = round(365 / ratios['ar_turnover'], 1)
        else:
            ratios['ar_days'] = None

        results.append(ratios)

    return results[-quarters_back:]


# ============================================================
# 预警生成
# ============================================================

ALERT_NONE = '正常'
ALERT_WATCH = '关注'
ALERT_WARN = '预警'
ALERT_SEVERE = '严重预警'


def generate_alerts(quarterly_data, yoy_data, ratio_data, dates):
    """生成预警列表"""
    alerts = []

    # --- 1. 营收动能趋势 ---
    rev_yoy = yoy_data['revenue_yoy']
    rev_trend = detect_trend(rev_yoy, 3)
    rev_declining_count = count_consecutive_declining(rev_yoy)
    rev_turn_neg = check_turn_negative(rev_yoy)
    rev_neg_streak = check_negative_streak(rev_yoy, 2)

    if rev_neg_streak:
        level = ALERT_SEVERE
        detail = f'YoY 连续 {sum(1 for v in rev_yoy if v is not None and v < 0)} 个季度为负'
    elif rev_turn_neg:
        level = ALERT_WARN
        detail = 'YoY 由正转负'
    elif rev_declining_count >= 3:
        level = ALERT_WARN
        detail = f'YoY 连续 {rev_declining_count} 季度减速'
    elif rev_declining_count >= 2:
        level = ALERT_WATCH
        detail = f'YoY 连续 {rev_declining_count} 季度减速'
    else:
        level = ALERT_NONE
        detail = '增长趋势正常'

    alerts.append({
        'check': '营收增长动能趋势',
        'status': rev_trend,
        'level': level,
        'detail': detail,
    })

    # --- 2. 扣非净利润趋势 ---
    np_yoy = yoy_data['deducted_np_yoy']
    np_trend = detect_trend(np_yoy, 3)
    np_declining_count = count_consecutive_declining(np_yoy)

    latest_np_yoy = next((v for v in reversed(np_yoy) if v is not None), None)
    if latest_np_yoy is not None and latest_np_yoy < -30:
        level = ALERT_WARN
        detail = f'最新季度扣非NP YoY = {latest_np_yoy}%（大幅下滑）'
    elif np_declining_count >= 3:
        level = ALERT_WARN
        detail = f'YoY 连续 {np_declining_count} 季度减速'
    elif np_declining_count >= 2:
        level = ALERT_WATCH
        detail = f'YoY 连续 {np_declining_count} 季度减速'
    else:
        level = ALERT_NONE
        detail = '扣非利润趋势正常'

    alerts.append({
        'check': '扣非净利润趋势',
        'status': np_trend,
        'level': level,
        'detail': detail,
    })

    # --- 3. 盈利质量 ---
    latest_np = next((v for v in reversed(quarterly_data['np']) if v is not None), None)
    latest_deducted = next((v for v in reversed(quarterly_data['deducted_np']) if v is not None), None)
    if latest_np is not None and latest_deducted is not None and abs(latest_np) > 0:
        gap_ratio = abs(latest_np - latest_deducted) / abs(latest_np) * 100
        if gap_ratio > 30:
            level = ALERT_WARN
            detail = f'归母NP与扣非NP差额占归母NP {gap_ratio:.1f}%，非经常性损益影响较大'
        elif gap_ratio > 15:
            level = ALERT_WATCH
            detail = f'差额占比 {gap_ratio:.1f}%'
        else:
            level = ALERT_NONE
            detail = f'差额占比 {gap_ratio:.1f}%，盈利质量正常'
    else:
        level = ALERT_NONE
        detail = '数据不足'
        gap_ratio = None

    alerts.append({
        'check': '盈利质量（非经常性损益）',
        'status': 'info',
        'level': level,
        'detail': detail,
    })

    # --- 4. 经营现金流趋势 ---
    ocf = quarterly_data['ocf']
    ocf_trend = detect_trend(ocf, 3)
    latest_ocf = next((v for v in reversed(ocf) if v is not None), None)
    neg_count = sum(1 for v in ocf[-4:] if v is not None and v < 0)

    if neg_count >= 2:
        level = ALERT_SEVERE
        detail = f'近4季中 {neg_count} 季经营现金流为负'
    elif latest_ocf is not None and latest_ocf < 0:
        level = ALERT_WARN
        detail = '最新季度经营现金流为负'
    elif ocf_trend == 'declining':
        level = ALERT_WATCH
        detail = '经营现金流呈下降趋势'
    else:
        level = ALERT_NONE
        detail = '现金流趋势正常'

    # 现金流/利润背离
    latest_np_val = next((v for v in reversed(quarterly_data['np']) if v is not None), None)
    if latest_ocf is not None and latest_np_val is not None and latest_np_val > 0:
        ocf_np_ratio = latest_ocf / latest_np_val
        if ocf_np_ratio < 0.5 and ocf_np_ratio >= 0:
            level = ALERT_WATCH if level == ALERT_NONE else level
            detail += f'；经营现金流/净利润 = {ocf_np_ratio:.2f}（利润现金含金量偏低）'

    alerts.append({
        'check': '经营现金流趋势',
        'status': ocf_trend,
        'level': level,
        'detail': detail,
    })

    # --- 5. 存货周期趋势 ---
    inv_yoy = yoy_data['inventory_yoy']
    if ratio_data:
        inv_days = [r.get('inventory_days') for r in ratio_data]
        inv_days_trend = detect_trend(inv_days, 3)
    else:
        inv_days_trend = 'insufficient_data'

    latest_inv_yoy = next((v for v in reversed(inv_yoy) if v is not None), None)
    if latest_inv_yoy is not None and latest_inv_yoy > 100:
        level = ALERT_WARN
        detail = f'存货 YoY +{latest_inv_yoy:.0f}%（高位积压）'
    elif inv_days_trend == 'declining':
        # 周转天数下降 = 改善；上升 = 恶化
        # detect_trend 返回 'declining' 表示数值递减
        # 但对周转天数，递减=改善，递增=恶化
        pass
    if inv_days_trend == 'improving':
        # 周转天数递增 = 恶化
        level = ALERT_WATCH
        detail = '存货周转天数持续上升'
    elif latest_inv_yoy is not None and latest_inv_yoy > 50:
        level = ALERT_WATCH
        detail = f'存货 YoY +{latest_inv_yoy:.0f}%'
    else:
        level = ALERT_NONE
        detail = '存货周期正常'

    alerts.append({
        'check': '存货周期趋势',
        'status': inv_days_trend,
        'level': level,
        'detail': detail,
    })

    # --- 6. 财务比率健康度 ---
    if ratio_data:
        # 总资产周转率趋势
        tat = [r.get('total_asset_turnover') for r in ratio_data]
        tat_trend = detect_trend(tat, 3)
        # 存货周转率趋势
        it = [r.get('inventory_turnover') for r in ratio_data]
        it_trend = detect_trend(it, 3)
        # 应收账款周转率趋势
        art = [r.get('ar_turnover') for r in ratio_data]
        art_trend = detect_trend(art, 3)
        # 流动比率趋势
        cr = [r.get('current_ratio') for r in ratio_data]
        cr_trend = detect_trend(cr, 3)
        # 速动比率趋势
        qr = [r.get('quick_ratio') for r in ratio_data]
        qr_trend = detect_trend(qr, 3)

        # 汇总比率预警
        declining_ratios = []
        if tat_trend == 'declining':
            declining_ratios.append('总资产周转率')
        if it_trend == 'declining':
            declining_ratios.append('存货周转率')
        if art_trend == 'declining':
            declining_ratios.append('应收账款周转率')
        if cr_trend == 'declining':
            declining_ratios.append('流动比率')
        if qr_trend == 'declining':
            declining_ratios.append('速动比率')

        if len(declining_ratios) >= 3:
            level = ALERT_WARN
            detail = f'{", ".join(declining_ratios)} 连续3季恶化'
        elif len(declining_ratios) >= 1:
            level = ALERT_WATCH
            detail = f'{", ".join(declining_ratios)} 呈下降趋势'
        else:
            level = ALERT_NONE
            detail = '财务比率趋势稳定'

        alerts.append({
            'check': '总资产周转率趋势',
            'status': tat_trend,
            'level': ALERT_WATCH if tat_trend == 'declining' else ALERT_NONE,
            'detail': f'趋势: {tat_trend}',
        })
        alerts.append({
            'check': '存货周转率趋势',
            'status': it_trend,
            'level': ALERT_WATCH if it_trend == 'declining' else ALERT_NONE,
            'detail': f'趋势: {it_trend}',
        })
        alerts.append({
            'check': '应收账款周转率趋势',
            'status': art_trend,
            'level': ALERT_WATCH if art_trend == 'declining' else ALERT_NONE,
            'detail': f'趋势: {art_trend}',
        })
        alerts.append({
            'check': '流动比率趋势',
            'status': cr_trend,
            'level': ALERT_WATCH if cr_trend == 'declining' else ALERT_NONE,
            'detail': f'趋势: {cr_trend}',
        })
        alerts.append({
            'check': '速动比率趋势',
            'status': qr_trend,
            'level': ALERT_WATCH if qr_trend == 'declining' else ALERT_NONE,
            'detail': f'趋势: {qr_trend}',
        })
    else:
        for name in ['总资产周转率', '存货周转率', '应收账款周转率', '流动比率', '速动比率']:
            alerts.append({
                'check': f'{name}趋势',
                'status': 'insufficient_data',
                'level': ALERT_NONE,
                'detail': '数据不足',
            })

    # --- 11. 增收不增利检测（量利剪刀差） ---
    rev_y = yoy_data['revenue_yoy']
    np_y = yoy_data['deducted_np_yoy']
    diff = [(rev_y[i] - np_y[i]) if (rev_y[i] is not None and np_y[i] is not None) else None
            for i in range(len(rev_y))]
    diff_valid = [d for d in diff if d is not None]
    diff_trend = detect_trend(diff, 3)
    pos_recent = sum(1 for d in diff_valid[-4:] if d is not None and d > 0)
    expanding = False
    if len(diff_valid) >= 3:
        last3 = diff_valid[-3:]
        expanding = (all(d > 0 for d in last3) and
                     all(last3[i] <= last3[i + 1] for i in range(len(last3) - 1)))
    if pos_recent >= 3 and expanding:
        level = ALERT_WARN
        detail = f'营收YoY持续高于扣非NP YoY，增收不增利趋势确立（近{pos_recent}季差值为正且扩大）'
    elif pos_recent >= 2:
        level = ALERT_WATCH
        detail = f'近{pos_recent}季营收增速高于利润增速'
    elif len(diff_valid) >= 2 and diff_valid[-2] is not None and diff_valid[-1] is not None \
            and diff_valid[-2] <= 0 < diff_valid[-1]:
        level = ALERT_WATCH
        detail = '量利剪刀差由负转正（利润增速开始慢于收入增速）'
    else:
        level = ALERT_NONE
        detail = '利润增速与收入增速匹配'
    alerts.append({'check': '增收不增利检测（量利剪刀差）', 'status': diff_trend, 'level': level, 'detail': detail})

    # --- 12. 资产减值趋势 ---
    impair = quarterly_data.get('asset_impairment', [])
    rev_q = quarterly_data['revenue']
    impair_ratio = []
    for i in range(len(rev_q)):
        if i < len(impair) and impair[i] is not None and rev_q[i] not in (None, 0):
            impair_ratio.append(round(impair[i] / abs(rev_q[i]) * 100, 2))
        else:
            impair_ratio.append(None)
    ir_trend = detect_trend(impair_ratio, 3)
    ir_valid = [v for v in impair_ratio if v is not None]
    latest_ir = next((v for v in reversed(ir_valid)), None)
    last3_ir = [v for v in impair_ratio[-3:] if v is not None]
    if ir_trend == 'improving' and latest_ir is not None and latest_ir > 3 and len(last3_ir) >= 3:
        level = ALERT_WARN
        detail = f'减值/营收占比连续上升且最新 {latest_ir:.1f}%'
    elif ir_trend == 'improving':
        level = ALERT_WATCH
        detail = '减值/营收占比连续上升'
    elif (latest_ir is not None and len(ir_valid) >= 2 and ir_valid[-2] is not None
          and ir_valid[-2] > 0 and ir_valid[-1] > ir_valid[-2] * 2):
        level = ALERT_WATCH
        detail = f'单季减值占比突变至 {latest_ir:.1f}%'
    else:
        level = ALERT_NONE
        detail = '减值趋势稳定或下降'
    alerts.append({'check': '资产减值趋势', 'status': ir_trend, 'level': level, 'detail': detail})

    # --- 13. 合同负债/预收趋势（前瞻需求） ---
    cl = quarterly_data.get('contract_liability', [])
    cl_valid = [v for v in cl if v is not None]
    if len(cl_valid) >= 3:
        cl_yoy = compute_yoy_series(cl)
        cl_yoy_valid = [v for v in cl_yoy if v is not None]
        neg_yoy = sum(1 for v in cl_yoy_valid[-3:] if v is not None and v < 0)
        cl_trend = detect_trend(cl, 3)
        if neg_yoy >= 3:
            level = ALERT_WARN
            detail = f'合同负债同比连续 {neg_yoy} 季下降（前瞻需求走弱）'
        elif neg_yoy >= 2:
            level = ALERT_WATCH
            detail = f'合同负债近 {neg_yoy} 季同比下降'
        else:
            level = ALERT_NONE
            detail = '合同负债趋势稳定或上升'
    else:
        cl_trend = 'insufficient_data'
        level = ALERT_NONE
        detail = '合同负债数据不足或不适用（如无预收模式）'
    alerts.append({'check': '合同负债/预收趋势（前瞻需求）', 'status': cl_trend, 'level': level, 'detail': detail})

    # --- 14. 存货积压风险（结构校验） ---
    inv_yoy = yoy_data['inventory_yoy']
    gap = [(inv_yoy[i] - rev_y[i]) if (inv_yoy[i] is not None and rev_y[i] is not None) else None
           for i in range(len(inv_yoy))]
    gap_valid = [g for g in gap if g is not None]
    high_gap = sum(1 for g in gap_valid[-3:] if g is not None and g > 20)
    gap_trend = detect_trend(gap, 3)
    if high_gap >= 3:
        level = ALERT_WARN
        detail = '存货增速连续3季显著高于营收增速（>20pct），积压风险'
    elif high_gap >= 1:
        level = ALERT_WATCH
        detail = f'存货增速高于营收增速（近{high_gap}季差值>20pct，需结合合同负债/在手订单判断备货 vs 积压）'
    else:
        level = ALERT_NONE
        detail = '存货增速与营收增速匹配'
    alerts.append({'check': '存货积压风险（结构校验）', 'status': gap_trend, 'level': level, 'detail': detail})

    return alerts


# ============================================================
# 格式化输出
# ============================================================

def format_wan(val):
    """格式化为万元"""
    if val is None:
        return '—'
    return f'{val / 10000:.0f}'


def format_pct(val):
    """格式化为百分比"""
    if val is None:
        return '—'
    sign = '+' if val >= 0 else ''
    return f'{sign}{val:.1f}%'


def format_ratio(val):
    """格式化比率"""
    if val is None:
        return '—'
    return f'{val:.2f}'


def output_report(dates, quarterly_data, yoy_data, ratio_data, alerts):
    """输出 markdown 格式报告"""
    lines = []
    lines.append('## 业绩动能（因子 13）检查报告')
    lines.append('')

    # 显示最近4个季度的数据
    recent_dates = dates[-4:]
    n = len(recent_dates)

    # 1. 营收与利润
    lines.append('### 1. 营收与利润趋势（近4季度）')
    lines.append('')
    lines.append('| 季度 | 营收(万) | 营收YoY | 归母NP(万) | NP YoY | 扣非NP(万) | 扣非NP YoY |')
    lines.append('|------|---------|---------|-----------|--------|-----------|------------|')
    for i in range(-n, 0):
        d = dates[i]
        lines.append(f'| {d[:7]} | {format_wan(quarterly_data["revenue"][i])} | {format_pct(yoy_data["revenue_yoy"][i])} '
                     f'| {format_wan(quarterly_data["np"][i])} | {format_pct(yoy_data["np_yoy"][i])} '
                     f'| {format_wan(quarterly_data["deducted_np"][i])} | {format_pct(yoy_data["deducted_np_yoy"][i])} |')
    lines.append('')

    # 2. 现金流
    lines.append('### 2. 经营现金流趋势（近4季度）')
    lines.append('')
    lines.append('| 季度 | 经营现金流(万) |')
    lines.append('|------|---------------|')
    for i in range(-n, 0):
        lines.append(f'| {dates[i][:7]} | {format_wan(quarterly_data["ocf"][i])} |')
    lines.append('')

    # 3. 财务比率
    if ratio_data:
        lines.append('### 3. 财务比率趋势（近4季度，TTM制）')
        lines.append('')
        lines.append('| 季度 | 总资产周转率 | 存货周转率 | 存货周转天数 | 应收账款周转率 | 应收账款周转天数 | 流动比率 | 速动比率 |')
        lines.append('|------|------------|-----------|-------------|--------------|-----------------|---------|---------|')
        for r in ratio_data:
            lines.append(f'| {r["date"][:7]} | {format_ratio(r.get("total_asset_turnover"))} '
                        f'| {format_ratio(r.get("inventory_turnover"))} | {r.get("inventory_days") or "—"} '
                        f'| {format_ratio(r.get("ar_turnover"))} | {r.get("ar_days") or "—"} '
                        f'| {format_ratio(r.get("current_ratio"))} | {format_ratio(r.get("quick_ratio"))} |')
        lines.append('')

    # 4. 存货
    lines.append('### 4. 存货趋势（近4季度）')
    lines.append('')
    lines.append('| 季度 | 存货(万) | 存货YoY |')
    lines.append('|------|---------|---------|')
    for i in range(-n, 0):
        lines.append(f'| {dates[i][:7]} | {format_wan(quarterly_data["inventory"][i])} | {format_pct(yoy_data["inventory_yoy"][i])} |')
    lines.append('')

    # 4b. 盈利质量与前瞻指标（增收不增利/减值/合同负债/存货积压）
    lines.append('### 4b. 盈利质量与前瞻指标（近4季度）')
    lines.append('')
    impair = quarterly_data.get('asset_impairment', [])
    cl = quarterly_data.get('contract_liability', [])
    inv_yoy = yoy_data['inventory_yoy']
    rev_y = yoy_data['revenue_yoy']
    lines.append('| 季度 | 量利剪刀差(营收YoY−扣非NP YoY) | 资产减值(万) | 减值/营收 | 合同负债(万) | 存货YoY−营收YoY |')
    lines.append('|------|------------------------------|------------|----------|------------|----------------|')
    for i in range(-n, 0):
        ryy = yoy_data['revenue_yoy'][i]
        dny = yoy_data['deducted_np_yoy'][i]
        sc = f'{ryy - dny:+.1f}%' if (ryy is not None and dny is not None) else '—'
        im = impair[i] if i < len(impair) else None
        ir = (im / abs(quarterly_data['revenue'][i]) * 100) if (im is not None and quarterly_data['revenue'][i] not in (None, 0)) else None
        irs = f'{ir:.2f}%' if ir is not None else '—'
        invy = inv_yoy[i]
        revy = rev_y[i]
        gv = f'{invy - revy:+.1f}pct' if (invy is not None and revy is not None) else '—'
        lines.append(f'| {dates[i][:7]} | {sc} | {format_wan(im)} | {irs} | {format_wan(cl[i] if i < len(cl) else None)} | {gv} |')
    lines.append('')

    # 5. 预警汇总
    lines.append('### 5. 预警汇总')
    lines.append('')
    lines.append('| 检查项 | 趋势 | 预警等级 | 说明 |')
    lines.append('|--------|------|----------|------|')
    for a in alerts:
        lines.append(f'| {a["check"]} | {a["status"]} | {a["level"]} | {a["detail"]} |')
    lines.append('')

    # 6. 对多空结论的影响
    triggered = [a for a in alerts if a['level'] in (ALERT_WARN, ALERT_SEVERE)]
    watched = [a for a in alerts if a['level'] == ALERT_WATCH]
    if triggered:
        lines.append('### ⚠️ 业绩动能与多空因子结论存在背离')
        lines.append('')
        lines.append(f'结构类因子（行业/政策/壁垒等）的**中长期判断**与以下**短期业绩动能预警**存在背离：')
        lines.append('')
        for a in triggered:
            lines.append(f'- **{a["check"]}**：{a["detail"]}')
        lines.append('')
        lines.append('> **提示**：结构性因子（行业空间/政策/壁垒等）反映 3-5 年方向，')
        lines.append('> 业绩动能预警反映 1-3 个季度的战术性扰动。两者背离时，')
        lines.append('> 应在最终结论中明确标注"结构性利多与短期业绩存在背离"，')
        lines.append('> 并建议跟踪后续季度业绩是否企稳。')
    elif watched:
        lines.append('### 关注事项')
        lines.append('')
        for a in watched:
            lines.append(f'- {a["check"]}：{a["detail"]}')
    else:
        lines.append('### 业绩动能正常')
        lines.append('')
        lines.append('所有检查项均在正常范围内，未触发预警。')
    lines.append('')

    return '\n'.join(lines)


# ============================================================
# 主函数
# ============================================================

def main():
    if len(sys.argv) < 2:
        print('Usage: python3 momentum_calc.py <stock_code> [num_quarters]')
        print('Example: python3 momentum_calc.py sh688508')
        sys.exit(1)

    stock_code = sys.argv[1]
    num = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    if num < 8:
        num = 8
        print(f'[info] num_quarters 调整为 8（最少需要8季度数据做YoY趋势）')

    print(f'[info] 获取 {stock_code} 最近 {num} 个季度财务数据...')

    # 获取三大报表
    lrb_raw = fetch_finance_data(stock_code, 'lrb', num)
    zcfz_raw = fetch_finance_data(stock_code, 'zcfz', num)
    xjll_raw = fetch_finance_data(stock_code, 'xjll', num)

    lrb_rows = parse_markdown_table(lrb_raw)
    zcfz_rows = parse_markdown_table(zcfz_raw)
    xjll_rows = parse_markdown_table(xjll_raw)

    if not lrb_rows or not zcfz_rows:
        print('[error] 无法获取财务数据，请检查股票代码')
        sys.exit(1)

    dates = [r['_date'] for r in lrb_rows]
    print(f'[info] 获取到 {len(dates)} 个季度数据: {dates[0]} ~ {dates[-1]}')

    # --- 提取季度数据 ---
    # 营收（lrb 有 _Q 字段，直接用）
    revenue_q = [to_float(r.get('OperatingRevenue_Q')) for r in lrb_rows]
    # 归母NP
    np_q = [to_float(r.get('NPParentCompanyOwners_Q')) for r in lrb_rows]
    # 营业成本
    cost_q = [to_float(r.get('OperatingCost_Q')) for r in lrb_rows]

    # 扣非NP（zcfz 有 NPDeductNonRecurringPL，是累计值，需转季度）
    deducted_cumulative = [to_float(r.get('NPDeductNonRecurringPL')) for r in zcfz_rows]
    deducted_q = compute_quarterly_from_cumulative(deducted_cumulative, dates)

    # 经营现金流（xjll 有 _Q 字段）
    ocf_q = []
    for r in xjll_rows:
        val = to_float(r.get('NetOperateCashFlow_Q'))
        if val is None:
            # 尝试从累计值计算
            val_cumulative = to_float(r.get('NetOperateCashFlow'))
            ocf_q.append(val_cumulative)  # 先放累计，后面统一转
        else:
            ocf_q.append(val)

    # 如果 ocf_q 是累计值（没有 _Q），转季度
    if xjll_rows and 'NetOperateCashFlow_Q' not in str(xjll_raw[:500]):
        ocf_q = compute_quarterly_from_cumulative(ocf_q, dates)

    # 存货（资产负债表，期末值）
    inventory = [to_float(r.get('Inventories')) for r in zcfz_rows]

    # 资产减值损失（利润表：优先 _Q 单季，否则累计值转单季）
    impair_q_list = [to_float(r.get('AssetImpairmentLoss_Q')) for r in lrb_rows]
    if all(v is None for v in impair_q_list):
        impair_cum = [to_float(r.get('AssetImpairmentLoss')) for r in lrb_rows]
        asset_impairment = compute_quarterly_from_cumulative(impair_cum, dates)
    else:
        asset_impairment = impair_q_list

    # 合同负债/预收款（资产负债表，期末值）
    contract_liability = [to_float(r.get('ContractLiability')) for r in zcfz_rows]

    # --- 计算 YoY ---
    revenue_yoy = compute_yoy_series(revenue_q)
    np_yoy = compute_yoy_series(np_q)
    deducted_np_yoy = compute_yoy_series(deducted_q)
    inventory_yoy = compute_yoy_series(inventory)

    quarterly_data = {
        'revenue': revenue_q,
        'np': np_q,
        'deducted_np': deducted_q,
        'ocf': ocf_q,
        'inventory': inventory,
        'asset_impairment': asset_impairment,
        'contract_liability': contract_liability,
    }

    yoy_data = {
        'revenue_yoy': revenue_yoy,
        'np_yoy': np_yoy,
        'deducted_np_yoy': deducted_np_yoy,
        'inventory_yoy': inventory_yoy,
    }

    # --- 计算财务比率 ---
    ratio_data = compute_turnover_ratios(lrb_rows, zcfz_rows, quarters_back=4)

    # --- 生成预警 ---
    alerts = generate_alerts(quarterly_data, yoy_data, ratio_data, dates)

    # --- 输出报告 ---
    report = output_report(dates, quarterly_data, yoy_data, ratio_data, alerts)
    print()
    print(report)


if __name__ == '__main__':
    main()
