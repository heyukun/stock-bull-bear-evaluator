#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多空评级加权打分计算器（三时间框架）

用法:
    python3 scoring_calc.py input.json [-c config.json] [--md out.md]
    python3 scoring_calc.py --demo
    python3 scoring_calc.py --print-config

输入 JSON 格式见 references/scoring-algorithm.md 第 6.2 节。
仅依赖 Python 标准库。
"""

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(BASE_DIR, "config", "scoring-config.json")

FRAMES = ("current", "mid", "long")
NEUTRAL_SCORE = 5.5
TOLERANCE = 1e-4
BREAKER_SCORE = -1.0  # 尾部风险熔断触发时的综合评分哨兵值（加权结果作废）

DEMO_INPUT = {
    "company": "示例公司（演示数据）",
    "code": "sz000000",
    "date": "2026-08-16",
    "factors": {
        "宏观":            {"current": "中性偏多", "mid": "向好",   "long": "中性偏多"},
        "社会舆论":        {"current": "中性",     "mid": "不明朗", "long": "中性"},
        "行业":            {"current": "利多",     "mid": "向好",   "long": "利多"},
        "政策":            {"current": "中性",     "mid": "向好",   "long": "中性偏多"},
        "上游":            {"current": "中性偏空", "mid": "不明朗", "long": "中性"},
        "下游":            {"current": "利多",     "mid": "向好",   "long": "利多"},
        "竞争对手":        {"current": "中性偏多", "mid": "不明朗", "long": "中性"},
        "替代品/新技术颠覆": {"current": "中性",     "mid": "不明朗", "long": "中性偏空"},
        "进入壁垒":        {"current": "利多",     "mid": "不明朗", "long": "利多"},
        "公司资本操作":    {"current": "中性偏多", "mid": "向好",   "long": "中性偏多"},
        "筹码多空":        {"current": "中性",     "mid": "不明朗", "long": "中性"},
        "资金多空":        {"current": "中性偏多", "mid": "向好",   "long": "中性"},
        "业绩动能":        {"current": "中性偏多", "mid": "向好",   "long": "中性"},
        "估值":            {"current": "中性偏空", "mid": "不明朗", "long": "中性"}
    }
}


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    validate_config(cfg, path)
    return cfg


def validate_config(cfg, path):
    """校验配置完整性: 因子清单、档位映射、权重归一、阈值覆盖。"""
    factors = cfg.get("factors")
    if not factors or not isinstance(factors, list):
        raise ValueError("config.factors 必须为非空列表")

    levels = cfg.get("level_scores")
    if not levels:
        raise ValueError("config.level_scores 缺失")
    for lv in ("利多", "中性偏多", "中性", "中性偏空", "利空", "向好", "不明朗", "不佳"):
        if lv not in levels:
            raise ValueError("level_scores 缺少档位: %s" % lv)

    frames = cfg.get("frames")
    if not frames or any(k not in frames for k in FRAMES):
        raise ValueError("config.frames 必须包含 current/mid/long 三个框架")

    fw_total = 0.0
    for fk in FRAMES:
        fr = frames[fk]
        label = fr.get("label", fk)
        fw = fr.get("weight")
        if not isinstance(fw, (int, float)) or isinstance(fw, bool) or fw < 0:
            raise ValueError("框架[%s]缺少合法的框架权重 weight（须为非负数字）" % label)
        w = fr.get("factor_weights", {})
        missing = [f for f in factors if f not in w]
        if missing:
            raise ValueError("框架[%s]缺少因子权重: %s" % (label, ", ".join(missing)))
        extra = [f for f in w if f not in factors]
        if extra:
            raise ValueError("框架[%s]含未知因子: %s" % (label, ", ".join(extra)))
        s = sum(w.values())
        if abs(s - 1.0) > TOLERANCE:
            raise ValueError("框架[%s]因子权重之和为 %.4f, 必须等于 1.0" % (label, s))
        fw_total += fw
    if abs(fw_total - 1.0) > TOLERANCE:
        raise ValueError("三框架权重之和为 %.4f, 必须等于 1.0" % fw_total)

    th = cfg.get("rating_thresholds")
    if not th:
        raise ValueError("config.rating_thresholds 缺失")
    mins = [t["min"] for t in th]
    if mins != sorted(mins, reverse=True) or mins[-1] != 0.0 or mins[0] > 10.0:
        raise ValueError("rating_thresholds 必须严格递减、覆盖 [0,10] 且最小值为 0")


def resolve_score(value, level_scores, ctx):
    """档位字符串→分值; 数字直接使用; 结果 clamp 到 [1,10]。"""
    if isinstance(value, str):
        v = value.strip()
        if v not in level_scores:
            raise ValueError("%s: 未知档位 '%s'（合法档位见 config.level_scores）" % (ctx, value))
        score = float(level_scores[v])
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        score = float(value)
    else:
        raise ValueError("%s: 非法取值 %r（须为档位字符串或 1-10 数字）" % (ctx, value))
    return max(1.0, min(10.0, score))


def rating_of(score, thresholds):
    for t in thresholds:
        if score >= t["min"]:
            return t["label"]
    return thresholds[-1]["label"]


def compute(data, cfg):
    factors = cfg["factors"]
    level_scores = cfg["level_scores"]
    frames_cfg = cfg["frames"]
    thresholds = cfg["rating_thresholds"]

    input_factors = data.get("factors")
    if not input_factors:
        raise ValueError("输入缺少 factors")
    missing = [f for f in factors if f not in input_factors]
    if missing:
        raise ValueError("输入缺少因子: %s" % ", ".join(missing))

    warnings = []
    # 解析每个因子每个框架的得分
    scores = {}  # scores[factor][frame] = (raw, score)
    for f in factors:
        entry = input_factors[f]
        if not isinstance(entry, dict):
            raise ValueError("因子[%s]取值必须为对象 {current/mid/long}" % f)
        scores[f] = {}
        for fk in FRAMES:
            if fk not in entry or entry[fk] is None:
                scores[f][fk] = (None, NEUTRAL_SCORE)
                warnings.append("因子[%s]框架[%s]缺失, 按'中性'%.1f分计" % (f, fk, NEUTRAL_SCORE))
            else:
                sc = resolve_score(entry[fk], level_scores, "因子[%s]框架[%s]" % (f, fk))
                scores[f][fk] = (entry[fk], sc)

    # 各框架加权得分
    frame_results = {}
    for fk in FRAMES:
        fr = frames_cfg[fk]
        rows = []
        total = 0.0
        for f in factors:
            raw, sc = scores[f][fk]
            w = fr["factor_weights"][f]
            contrib = sc * w
            total += contrib
            rows.append({"factor": f, "raw": raw if raw is not None else "中性(默认)",
                         "score": sc, "weight": w, "contrib": contrib})
        frame_results[fk] = {
            "label": fr.get("label", fk),
            "weight": fr["weight"],
            "rows": rows,
            "score": total,
            "rating": rating_of(total, thresholds),
        }

    # 综合加权总分
    composite = sum(frame_results[fk]["score"] * frame_results[fk]["weight"] for fk in FRAMES)
    raw_rating = rating_of(composite, thresholds)

    # 尾部风险熔断：不参与加权；触发时综合评分记为 BREAKER_SCORE(-1)，评级封顶 cap_rating
    breakers = []
    for b in data.get("circuit_breakers") or []:
        if isinstance(b, str):
            breakers.append({"item": b, "evidence": ""})
        elif isinstance(b, dict):
            breakers.append({"item": str(b.get("item", "未命名熔断项")), "evidence": str(b.get("evidence", ""))})
    final_rating = raw_rating
    cap_rating = cfg.get("circuit_breaker", {}).get("cap_rating")
    if breakers and cap_rating:
        order = [t["label"] for t in thresholds]
        if cap_rating in order and raw_rating in order and order.index(raw_rating) < order.index(cap_rating):
            final_rating = cap_rating
    # 熔断触发时综合评分记为 -1（哨兵值，表示加权结果被一票否决）
    final_composite = BREAKER_SCORE if breakers else composite

    return {
        "company": data.get("company", "未命名"),
        "code": data.get("code", ""),
        "date": data.get("date", ""),
        "frames": frame_results,
        "composite": final_composite,
        "raw_composite": composite,
        "composite_rating": final_rating,
        "raw_rating": raw_rating,
        "circuit_breakers": breakers,
        "config_version": cfg.get("version", ""),
        "warnings": warnings,
    }


def fmt(x):
    s = "%.2f" % x
    return s.rstrip("0").rstrip(".") if "." in s else s


def pct(w):
    return "%.0f%%" % (w * 100)


def render_markdown(res):
    lines = []
    title = res["company"] + ("（%s）" % res["code"] if res["code"] else "")
    lines.append("### 加权多空评分：%s" % title)
    if res["date"]:
        lines.append("")
        lines.append("> 评估日期：%s ｜ 评分配置版本：%s" % (res["date"], res["config_version"]))
    lines.append("")

    for fk in FRAMES:
        fr = res["frames"][fk]
        lines.append("#### %s（框架权重 %s）" % (fr["label"], pct(fr["weight"])))
        lines.append("")
        lines.append("| 因子 | 档位 | 得分 | 因子权重 | 加权贡献 |")
        lines.append("|------|------|------|----------|----------|")
        for r in fr["rows"]:
            raw = r["raw"] if isinstance(r["raw"], str) else fmt(r["raw"]) if r["raw"] is not None else "—"
            lines.append("| %s | %s | %s | %s | %s |" % (
                r["factor"], raw, fmt(r["score"]), pct(r["weight"]), fmt(r["contrib"])))
        lines.append("| **框架得分** | | | **100%%** | **%.2f** |" % fr["score"])
        lines.append("")
        lines.append("**%s 得分：%.2f / 10 → 评级：%s**" % (fr["label"], fr["score"], fr["rating"]))
        lines.append("")

    lines.append("#### 综合加权总分")
    lines.append("")
    lines.append("| 时间框架 | 得分 | 框架权重 | 加权贡献 | 框架评级 |")
    lines.append("|----------|------|----------|----------|----------|")
    for fk in FRAMES:
        fr = res["frames"][fk]
        lines.append("| %s | %.2f | %s | %.2f | %s |" % (
            fr["label"], fr["score"], pct(fr["weight"]), fr["score"] * fr["weight"], fr["rating"]))
    tripped = bool(res.get("circuit_breakers"))
    comp_disp = "-1" if tripped else "%.2f" % res["composite"]
    lines.append("| **综合加权总分** | | **100%%** | **%s** | **%s** |" % (
        comp_disp, res["composite_rating"]))
    lines.append("")
    summary = "**综合加权总分：%s / 10 → 综合评级：%s**" % (comp_disp, res["composite_rating"])
    if tripped:
        summary += "（熔断触发，原始加权总分 %.2f 作废，按 -1 计）" % res["raw_composite"]
    else:
        summary += "（阈值：≥8.0 强烈看多 / 6.5-8.0 看多 / 4.5-6.5 中性 / 3.0-4.5 看空 / <3.0 强烈看空）"
    lines.append(summary)

    if tripped:
        lines.append("")
        lines.append("#### ⚠️ 尾部风险熔断触发（综合评分记为 -1）")
        lines.append("")
        lines.append("| 熔断项 | 证据 |")
        lines.append("|--------|------|")
        for b in res["circuit_breakers"]:
            lines.append("| %s | %s |" % (b["item"], b["evidence"] or "—"))
        lines.append("")
        lines.append("> 触发尾部风险熔断：综合评分结果按 **-1** 计（原始加权总分 %.2f），原始评级 **%s** 封顶为 **%s**（熔断项不参与加权，定义见 SKILL.md 第 5 步）。"
                     % (res["raw_composite"], res["raw_rating"], res["composite_rating"]))

    if res["warnings"]:
        lines.append("")
        lines.append("> ⚠️ %s" % "；".join(res["warnings"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="多空评级加权打分计算器")
    ap.add_argument("input", nargs="?", help="评估输入 JSON 文件路径")
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="评分配置 JSON（默认 config/scoring-config.json）")
    ap.add_argument("--md", help="将 markdown 结果写入指定文件")
    ap.add_argument("--demo", action="store_true", help="使用内置演示数据运行")
    ap.add_argument("--print-config", action="store_true", help="打印当前配置摘要并退出")
    args = ap.parse_args()

    cfg = load_config(args.config)

    if args.print_config:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0

    if args.demo:
        data = DEMO_INPUT
    elif args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        ap.error("须提供输入 JSON 文件，或使用 --demo / --print-config")
        return 2

    res = compute(data, cfg)
    md = render_markdown(res)
    print(md)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md + "\n")
        print("\n[已写入] %s" % args.md, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
