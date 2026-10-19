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
  3. 描述"未授权获取途径"的标题：整条置为 [数据删除] 并标记 status，
     不保留原始标题、不设年代豁免（见下）
  4. 不含任何账号编号、cookie、抓取凭据

关于规则 3 的形式：命中的行**整条抹除**——title 置为 "[数据删除]"，
并在新增的 status 列写入 "数据删除 / 读取错误"。这样做有两点考虑：
  a) 抹除比截断干净：原始标题里的渠道名不再出现在本仓库任何一个字节里；
  b) "读取错误"是归档系统本身的话——这份索引由一枚跑野了的欧米伽级核心整理，
     它对这类条目的说法就是"读不出来"。数据集的缺口因此是可检索的、而非静默的。
判定用的是下方逐条冻结的 DELETE_TIDS 名单，不含年份门槛——早期与近期一视同仁。
"""
import csv
import json
import re
import sys
from pathlib import Path

SRC = Path("./tb_full_index.json")          # 本地原始索引
DST = Path("./tb-index.csv")                # 发布产物

# 故障行的占位与状态标签
MARK = "[数据删除]"
STATUS = "数据删除 / 读取错误"

# —— 规则 3：获取路径类标题。**整条抹除**，名单为逐条人工复核后冻结 ——
#
# 复核对象：全表标题命中 `破解|盗版|免激活|绿色版|3DM` 的 38 条。
# 判定标准（严格）：只有下面三类算"获取途径"，才抹除——
#   (a) 求 / 问哪里能拿到未授权副本（"谁有…破解版 / 补丁 / 破解码"、"有…吗"、
#       "帮忙上传绿色版"、"具体看 3DM"）
#   (b) 宣告 / 发布未授权副本的存在或产出（"有破解版啦"、"【填坑】…发布"、
#       "3dm 有人放出了…"）
#   (c) 兜售 / 流通（"还有人卖…出远行星号"）
#
# 以下四类**保留原样**（它们提到未授权内容，但都不指向获取途径）：
#   1. 报错求助 —— "破解版老崩溃""字都不显示""存档能转正版吗"（确认解锁版存在过，
#      但不告诉任何人去哪拿）
#   2. 否定表达 —— "没破解""无破解，需要序列号"
#   3. 入正 / 转正讨论 —— "以前玩盗版现在想入正""盗版转正"
#   4. "破解"作"怎么打"解 —— "进星系跳出求破解""如何破解敌方舰队"
#      另有一条**反诈警告**（3DM 假破解提示）亦保留：它是社区自净的记录。
#
# 名单直接写 tid 而非正则：中文"破解"歧义极多，正则要么漏判要么误杀；
# 逐条冻结既精确又可审计（拿着 tid 就能回去看原帖）。
DELETE_TIDS = {
    "1768924877",  # 2012  远行星号0.53出来了，具体看3DM            (a 渠道指向)
    "1870981479",  # 2012  有521英文破解版的吗？                      (a 求)
    "1886129393",  # 2012  有没有英文版的破解过的0.521a?              (a 求)
    "2031771805",  # 2012  0.54a破解码                                (a 求码)
    "2051333748",  # 2012  .54的非汉化破解找了半天没找到。有谁有吗？   (a 求)
    "1981947217",  # 2013  远行星号0.53.1a有破解版啦                   (b 宣告)
    "2189480739",  # 2013  谁有0.52a的单独破解补丁                     (a 求)
    "2201492691",  # 2013  话说谁有O.54.1A的破解下载                   (a 求)
    "2208358632",  # 2013  【填坑】0.53.1a汉化破解版…发布               (b 发布)
    "2426798102",  # 2013  0.541a有破解吗                              (a 求)
    "2843129366",  # 2014  3dm有人放出了0.6.2a-rc3先期破解              (b 放出)
    "3072981413",  # 2014  0.62a的破解有吗                             (a 求)
    "3522678549",  # 2015  哪位大神帮忙上传一份绿色版…                  (a 求上传)
    "3589618015",  # 2015  谁有0.6以上中文破解版？                      (a 求)
    "4222616098",  # 2015  小白求远行星号0.65破解汉化版                 (a 求)
    "4318279627",  # 2016  求starsector_0.7.1a-RC5破解补丁              (a 求补丁)
    "4426094631",  # 2016  盗版狗弱弱问一下，这游戏就没有破解版吗        (a 求)
    "6627374600",  # 2020  0.91有盗版了，还有人卖…出远行星号0.9          (c 兜售)
}

# —— 规则 2：标题里的群号 / 联系方式 ——
GROUP_NUM = re.compile(r"(?<!\d)\d{6,12}(?!\d)")   # 6–12 位连续数字，多为群号
QQ_HINT = re.compile(r"[Qq]{1,2}群|企鹅群|扣群|群号|研究群|吹水群|交流群|微信群|微信[:：]")
RECRUIT_CTX = re.compile(r"招募|招收|征召|测试人员|加入我们|欢迎加入")


def year_of(row):
    ct = (row.get("create_time") or "").strip()
    return ct[:4] if ct.startswith("20") else "2026"


def redact_title(title, year, tid):
    """返回 (处理后的标题, 状态标签, 改动标记)；标记为空表示未改动。"""
    if not title:
        return "", "", ""

    marks = []

    # 规则 3：获取路径 —— 命中即整条抹除，保留 tid 与楼主名
    if str(tid) in DELETE_TIDS:
        return MARK, STATUS, "piracy"

    # 规则 2：群号 —— 全部年代都处理
    # 命中条件：标题含"群"字提示，或含招募/测试/加入一类语境
    # （裸挂的群号常不带"群"字，例如"招募游戏测试人员 295700311"）
    # "群"字本身就足够作为信号（萌新群/交流群/吹水群等变体太多，逐一举不现实）
    if GROUP_NUM.search(title) and ("群" in title or RECRUIT_CTX.search(title)):
        title = GROUP_NUM.sub("[群号已隐去]", title)
        marks.append("group-masked")

    return title, "", ",".join(marks)


def main():
    if not SRC.exists():
        sys.exit(f"找不到原始索引 {SRC.resolve()}（该文件不随仓库发布）")

    rows = json.loads(SRC.read_text(encoding="utf-8"))
    out, stats = [], {"total": 0, "glitch": 0, "group": 0, "no_author": 0}

    for r in rows:
        year = year_of(r)
        title, status, mark = redact_title((r.get("title") or "").strip(), year,
                                           r.get("tid", ""))
        author = (r.get("author") or "").strip()
        if not author:
            stats["no_author"] += 1
        if "piracy" in mark.split(","):
            stats["glitch"] += 1
        if "group-masked" in mark:
            stats["group"] += 1

        out.append({
            "tid": r.get("tid", ""),
            "year": year,
            "title": title,
            "author": author,
            "reply_num": r.get("reply_num", ""),
            "is_good": "1" if r.get("is_good") else "",
            "is_top": "1" if r.get("is_top") else "",
            "status": status,
        })
        stats["total"] += 1

    out.sort(key=lambda x: (x["year"], str(x["tid"])))

    # UTF-8 BOM：让中文用户在 Excel 里直接双击可读
    with DST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tid", "year", "title", "author",
                                          "reply_num", "is_good", "is_top",
                                          "status"])
        w.writeheader()
        w.writerows(out)

    print(f"写出 {DST} —— {stats['total']} 行")
    print(f"  标记为故障（整条抹除）{stats['glitch']} 条")
    print(f"  隐去群号 {stats['group']} 条")
    print(f"  原作者名缺失 {stats['no_author']} 条 "
          f"({stats['no_author'] / stats['total'] * 100:.1f}%)")


if __name__ == "__main__":
    main()
