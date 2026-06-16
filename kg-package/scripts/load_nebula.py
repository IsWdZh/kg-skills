# -*- coding: utf-8 -*-
"""服务态投影：把知识图谱（实体/关系/规则三元组）加载到 NebulaGraph。

用法: python load_nebula.py <工作区目录>

建模约定（与《知识资产存储规范化设计》§4.4 一致）:
- 只有"单实体→单实体"的关系才建直接边；含 AND/OR、多实体联合（如 E05+E07）的
  复合表达式建为"关系陈述"节点，经 involves 边挂到所涉实体，不伪造实体边；
- 规则（IF/THEN/EXCEPT）建为规则节点，经 based_on 边回链知识块，知识块经
  from_doc 边回链文档——支撑"政策变更影响分析"反向查询；
- 使用独立图空间 kg_gjj_trial，不触碰服务器上既有空间；
- NebulaGraph 标识符仅支持 ASCII，故 Tag/Edge/属性名用英文，值为中文。
  映射：entity=实体 rule=规则 rel_stmt=关系陈述 chunk=知识块 doc=文档；
       direct_rel=直接关系 involves=涉及 based_on=依据 from_doc=来源于
"""
import sys, json, re, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

NEBULA = dict(host="192.168.108.155", port=9669, user="root", password="root")
SPACE = "kg_gjj_trial"

SCHEMA = [
    "CREATE TAG IF NOT EXISTS entity(name string, type string, scene string, region string, version string, wiki_anchor string)",
    "CREATE TAG IF NOT EXISTS rule(name string, rule_text string, scene string, region string, version string)",
    "CREATE TAG IF NOT EXISTS rel_stmt(rel string, head_expr string, tail_expr string, scene string, region string, version string)",
    "CREATE TAG IF NOT EXISTS chunk(type string, scene string, region string)",
    "CREATE TAG IF NOT EXISTS doc(title string, region string, doc_type string, publish_date string)",
    "CREATE EDGE IF NOT EXISTS direct_rel(rel string)",
    "CREATE EDGE IF NOT EXISTS involves()",
    "CREATE EDGE IF NOT EXISTS based_on()",
    "CREATE EDGE IF NOT EXISTS from_doc(anchors string)",
]
INDEXES = [
    "CREATE TAG INDEX IF NOT EXISTS idx_entity ON entity()",
    "CREATE TAG INDEX IF NOT EXISTS idx_rule ON rule()",
    "CREATE TAG INDEX IF NOT EXISTS idx_rel_stmt ON rel_stmt()",
    "CREATE TAG INDEX IF NOT EXISTS idx_chunk ON chunk()",
    "CREATE TAG INDEX IF NOT EXISTS idx_doc ON doc()",
]


def esc(s) -> str:
    return (str(s if s is not None else "")
            .replace("\\", "\\\\").replace('"', '\\"')
            .replace("\r", "").replace("\n", "\\n").replace("\t", " "))


def jsonl(p: Path):
    with p.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def run(sess, stmt):
    rs = sess.execute(stmt)
    if not rs.is_succeeded():
        try:
            msg = rs.error_msg()
        except Exception:
            msg = repr(rs._resp.error_msg)
        raise RuntimeError(f"nGQL 失败: {msg}\n{stmt[:300]}")
    return rs


def batch_insert(sess, head, rows, batch=120):
    for i in range(0, len(rows), batch):
        run(sess, head + ", ".join(rows[i:i + batch]))


def main(ws: Path):
    from nebula3.gclient.net import ConnectionPool
    from nebula3.Config import Config
    ex = ws / "80-知识库导出" / "交换态"

    cfg = Config(); cfg.max_connection_pool_size = 2
    pool = ConnectionPool()
    assert pool.init([(NEBULA["host"], NEBULA["port"])], cfg), "连接失败"
    sess = pool.get_session(NEBULA["user"], NEBULA["password"])

    spaces = [r.values()[0].as_string() for r in run(sess, "SHOW SPACES")]
    print("服务器现有空间:", spaces)
    if SPACE not in spaces:
        run(sess, f"CREATE SPACE {SPACE}(partition_num=10, replica_factor=1, vid_type=FIXED_STRING(96))")
        print(f"已创建独立图空间 {SPACE}，等待元数据同步…")
        time.sleep(20)
    run(sess, f"USE {SPACE}")
    for s in SCHEMA:
        run(sess, s)
    print("Schema 就绪，等待心跳同步…")
    time.sleep(20)
    run(sess, f"USE {SPACE}")

    # ---- 顶点 ----
    ents = list(jsonl(ex / "图谱实体.jsonl"))
    batch_insert(sess, "INSERT VERTEX entity(name,type,scene,region,version,wiki_anchor) VALUES ",
        [f'"{esc(e["全局ID"])}":("{esc(e["名称"])}","{esc(e["类型"])}","{esc(e["场景编码"])}",'
         f'"{esc(e["地区码"])}","{esc(e["知识包版本"])}","{esc(e.get("Wiki锚点",""))}")' for e in ents])

    rules = list(jsonl(ex / "图谱规则.jsonl"))
    batch_insert(sess, "INSERT VERTEX rule(name,rule_text,scene,region,version) VALUES ",
        [f'"{esc(r["全局ID"])}":("{esc(r["规则名"])}","{esc(r["规则文本"])}","{esc(r["场景编码"])}",'
         f'"{esc(r["地区码"])}","{esc(r["知识包版本"])}")' for r in rules])

    kcs = list(jsonl(ex / "知识块.jsonl"))
    batch_insert(sess, "INSERT VERTEX chunk(type,scene,region) VALUES ",
        [f'"{esc(k["编号"])}":("{esc(k["类型"])}","{esc(k["场景编码"])}","{esc(k["地区码"])}")' for k in kcs])

    docs = list(jsonl(ex / "文档.jsonl"))
    batch_insert(sess, "INSERT VERTEX doc(title,region,doc_type,publish_date) VALUES ",
        [f'"{esc(d["编号"])}":("{esc(d["标题"])}","{esc(d["地区"])}","{esc(d["文档类型"])}",'
         f'"{esc(d["发布时间"])}")' for d in docs])

    # ---- 关系：单实体→单实体 建直接边；复合表达式建关系陈述节点 ----
    rels = list(jsonl(ex / "图谱关系.jsonl"))
    direct_edges, stmt_vertices, involve_edges, rel_based = [], [], [], []
    for r in rels:
        prefix = f'{r["场景编码"]}/{r["地区码"]}'
        h, t = r["头表达式"].strip(), r["尾表达式"].strip()
        gid = r["全局ID"]
        kc_list = r.get("来源知识块", [])
        if re.fullmatch(r"E\d+", h) and re.fullmatch(r"E\d+", t):
            direct_edges.append(f'"{prefix}/{h}"->"{prefix}/{t}":("{esc(r["关系"])}")')
            for kc in kc_list:
                rel_based.append((f"{prefix}/{h}", kc))  # 直接边的依据挂头实体（边无法再挂边）
        else:
            stmt_vertices.append(
                f'"{esc(gid)}":("{esc(r["关系"])}","{esc(h)}","{esc(t)}",'
                f'"{esc(r["场景编码"])}","{esc(r["地区码"])}","{esc(r["知识包版本"])}")')
            for eid in set(re.findall(r"E\d+", h + " " + t)):
                involve_edges.append(f'"{esc(gid)}"->"{prefix}/{eid}":()')
            for kc in kc_list:
                involve_edges_kc = f'"{esc(gid)}"->"{esc(kc)}":()'
                rel_based.append((gid, kc))
    if direct_edges:
        batch_insert(sess, "INSERT EDGE direct_rel(rel) VALUES ", direct_edges)
    if stmt_vertices:
        batch_insert(sess, "INSERT VERTEX rel_stmt(rel,head_expr,tail_expr,scene,region,version) VALUES ", stmt_vertices)
    if involve_edges:
        batch_insert(sess, "INSERT EDGE involves() VALUES ", involve_edges)

    # ---- 依据边：规则→知识块、关系陈述→知识块 ----
    based = [f'"{esc(r["全局ID"])}"->"{esc(kc)}":()' for r in rules for kc in r.get("来源知识块", [])]
    based += [f'"{esc(g)}"->"{esc(kc)}":()' for g, kc in rel_based]
    batch_insert(sess, "INSERT EDGE based_on() VALUES ", based)

    # ---- 来源边：知识块→文档（同一对多锚点合并为一条边）----
    pair_anchors = {}
    for k in kcs:
        for a in k.get("来源锚点", []):
            d = a.split("#")[0]
            pair_anchors.setdefault((k["编号"], d), []).append(a)
    batch_insert(sess, "INSERT EDGE from_doc(anchors) VALUES ",
        [f'"{esc(kc)}"->"{esc(d)}":("{esc("，".join(an))}")' for (kc, d), an in pair_anchors.items()])

    # ---- 索引 ----
    for s in INDEXES:
        run(sess, s)
    time.sleep(10)
    for name in ["idx_entity", "idx_rule", "idx_rel_stmt", "idx_chunk", "idx_doc"]:
        run(sess, f"REBUILD TAG INDEX {name}")
    print("索引重建已提交，等待完成…")
    time.sleep(15)

    # ---- 验证 ----
    print("\n=== 验证 ===")
    for tag, cn in [("entity", "实体"), ("rule", "规则"), ("rel_stmt", "关系陈述"),
                    ("chunk", "知识块"), ("doc", "文档")]:
        rs = run(sess, f"LOOKUP ON {tag} YIELD id(vertex) | YIELD COUNT(*)")
        print(f"{cn}({tag}): {rs.rows()[0].values[0].get_iVal()}")
    print("\n影响分析示例：JYG-001（2022新政）变更会波及——")
    rs = run(sess, 'GO FROM "JYG-001" OVER from_doc REVERSELY YIELD src(edge) AS kc'
                   ' | GO FROM $-.kc OVER based_on REVERSELY YIELD DISTINCT src(edge) AS 上游')
    for row in rs.rows():
        print("  ", row.values[0].get_sVal().decode())
    sess.release(); pool.close()


def derive_space(ws: Path) -> str:
    """从工作区名提取时间戳生成图空间名，与 load_pg 同源，便于对照。"""
    m = re.search(r"(\d{8})(?:[-_]?(\d{4,6}))?", ws.name)
    if m:
        return "kg_gjj_" + m.group(1) + ("_" + m.group(2) if m.group(2) else "")
    return SPACE


if __name__ == "__main__":
    argv = sys.argv
    pos = [a for a in argv[1:] if not a.startswith("--")]
    ws = Path(pos[0])
    if "--space" in argv:
        SPACE = argv[argv.index("--space") + 1]
    else:
        SPACE = derive_space(ws)
    print(f"目标图空间: {SPACE}（本次独立空间，与既有空间隔离）")
    main(ws)
