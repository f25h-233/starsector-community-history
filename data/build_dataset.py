#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把贴吧全量帖索引转成可公开的降敏数据集。

输入：tb_full_index.json（本地原始索引，不随本仓库发布）
      字段：tid / title / author / create_time / last_time / reply_num / is_good / is_top
输出：tb-index.csv（本仓库发布）

本脚本之所以一并放在仓库里，是为了让"到底删了什么、按什么规则删的"
完全可审计 —— 你有原始索引的话，直接跑一遍就能复现出同样的 CSV。

脱敏规则见 ../../脱敏与编辑政策.md，要点：
  1. 用户网名保留（这些名字本来就公开挂在每篇帖子上）
  2. 标题中的 QQ 群号 / 联系方式一律隐去（不设年代豁免）
  3. "求破解 / 找盗版"类**获取路径**：2020 年起一律过滤；
     2020 年前保留为历史记录（当年游戏处于 alpha、国内无正规渠道）
  4. 不含任何账号编号、cookie、抓取凭据
"""
import csv
import json
import re
import sys
from pathlib import Path

SRC = Path("./tb_full_index.json")          # 本地原始索引
DST = Path("./tb-index.csv")                # 发布产物

# —— 规则 3：获取路径类标题。严格词表，避免中文里"破解"= "怎么打" 的假阳性 ——
PIRACY = re.compile(
    r"破解版|破解补丁|破解汉化|破解码|破解下载|非汉化破解|的破解|破解的"
    r"|盗版|免激活|绿色版"
)
# 排除两类假阳性：
#   a) 中文里"破解"= "怎么打/怎么解"（进星系跳出求破解）
#   b) 游戏黑话"白嫖"（白嫖攻略/白嫖蓝图 = 免费蹭，与盗版无关）
#   c) 反盗版与入正讨论（举报盗版、以前玩盗版现在想入正）
FALSE_POSITIVE = re.compile(
    r"求破解$|如何破解|怎么破解|如何破|求破$|绝境|跳出"
    r"|白嫖|入正|举报|还有人卖|正版多少钱|盗版狗"
)

# —— 规则 2：标题里的群号 / 联系方式 ——
GROUP_NUM = re.compile(r"(?<!\d)\d{6,12}(?!\d)")   # 6–12 位连续数字，多为群号
QQ_HINT = re.compile(r"[Qq]{1,2}群|企鹅群|扣群|群号|研究群|吹水群|交流群|微信群|微信[:：]")
RECRUIT_CTX = re.compile(r"招募|招收|征召|测试人员|加入我们|欢迎加入")

PIRACY_CUTOFF = "2020"      # 此年份起的获取路径类标题将被过滤


def year_of(row):
    ct = (row.get("create_time") or "").strip()
    return ct[:4] if ct.startswith("20") else "2026"


def redact_title(title, year):
    """返回 (处理后的标题, 标记)；标记为空表示未改动。"""
    if not title:
        return "", ""

    marks = []

    # 规则 3：获取路径
    if PIRACY.search(title) and not FALSE_POSITIVE.search(title):
        if year >= PIRACY_CUTOFF:
            return "[标题已按脱敏政策隐去：涉及未授权获取途径]", "piracy"
        marks.append("historical-piracy")

    # 规则 2：群号 —— 全部年代都处理
    # 命中条件：标题含"群"字提示，或含招募/测试/加入一类语境
    # （裸挂的群号常不带"群"字，例如"招募游戏测试人员 295700311"）
    # "群"字本身就足够作为信号（萌新群/交流群/吹水群等变体太多，逐一举不现实）
    if GROUP_NUM.search(title) and ("群" in title or RECRUIT_CTX.search(title)):
        title = GROUP_NUM.sub("[群号已隐去]", title)
        marks.append("group-masked")

    return title, ",".join(marks)


def main():
    if not SRC.exists():
        sys.exit(f"找不到原始索引 {SRC.resolve()}（该文件不随仓库发布）")

    rows = json.loads(SRC.read_text(encoding="utf-8"))
    out, stats = [], {"total": 0, "piracy_cut": 0, "group": 0, "hist": 0, "no_author": 0}

    for r in rows:
        year = year_of(r)
        title, mark = redact_title((r.get("title") or "").strip(), year)
        author = (r.get("author") or "").strip()
        if not author:
            stats["no_author"] += 1
        if "piracy" in mark.split(","):
            stats["piracy_cut"] += 1
        if "group-masked" in mark:
            stats["group"] += 1
        if "historical-piracy" in mark:
            stats["hist"] += 1

        out.append({
            "tid": r.get("tid", ""),
            "year": year,
            "title": title,
            "author": author,
            "reply_num": r.get("reply_num", ""),
            "is_good": "1" if r.get("is_good") else "",
            "is_top": "1" if r.get("is_top") else "",
        })
        stats["total"] += 1

    out.sort(key=lambda x: (x["year"], str(x["tid"])))

    # UTF-8 BOM：让中文用户在 Excel 里直接双击可读
    with DST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tid", "year", "title", "author",
                                          "reply_num", "is_good", "is_top"])
        w.writeheader()
        w.writerows(out)

    print(f"写出 {DST} —— {stats['total']} 行")
    print(f"  按政策过滤标题 {stats['piracy_cut']} 条（{PIRACY_CUTOFF} 年起）")
    print(f"  隐去群号 {stats['group']} 条")
    print(f"  保留为历史记录 {stats['hist']} 条（{PIRACY_CUTOFF} 年前）")
    print(f"  原作者名缺失 {stats['no_author']} 条 "
          f"({stats['no_author'] / stats['total'] * 100:.1f}%)")


if __name__ == "__main__":
    main()
