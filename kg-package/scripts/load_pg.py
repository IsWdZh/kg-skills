# -*- coding: utf-8 -*-
"""服务态投影：把交换态 JSONL 加载到 PostgreSQL（知识数据）+ pgvector（知识向量）。

用法:
  python load_pg.py <工作区目录>            # 建库建表 + 加载知识数据 + 向量化
  python load_pg.py <工作区目录> --no-embed # 跳过向量化（无嵌入模型环境）

约定（与《知识资产存储规范化设计》一致）:
- 数据库为可重建投影：脚本幂等，重跑=清空重建（DROP SCHEMA 后重建），事实源永远是冻结知识包；
- 使用独立数据库 kg_gjj_trial，不触碰服务器上既有库（ai/nacos/ontology_db）；
- 表名列名全中文；编码/ID 保留 ASCII。
"""
import sys, json, os
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PG = dict(host="192.168.108.155", port=5432, user="pgsql", password="Jczh@2026")
DB_NAME = "kg_gjj_trial"
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"   # 512 维
EMBED_DIM = 512

DDL = """
CREATE TABLE 文档 (
    编号 text PRIMARY KEY, 标题 text NOT NULL, 地区 text, 发布机构 text, 文档类型 text,
    发布时间 text, 生效时间 text, 源文件 text, 内容哈希 text, 完整性 text,
    权限范围 text, 来源网址 text, 解析文件 text, 解析文件哈希 text);
CREATE TABLE 知识包 (
    包ID text PRIMARY KEY, 场景编码 text NOT NULL, 地区码 text NOT NULL, 版本 text NOT NULL,
    治理档位 text, 发布状态 text, 发布动作 text, 时效基准 text, 包清单 text, 包清单哈希 text);
CREATE TABLE 知识块 (
    编号 text PRIMARY KEY, 场景编码 text NOT NULL, 地区码 text NOT NULL, 知识包版本 text,
    类型 text, 标题 text, 内容 text NOT NULL, 适用范围 text, 时效说明 text, 快照文件 text);
CREATE TABLE 知识块来源 (
    知识块编号 text REFERENCES 知识块(编号), 锚点 text, PRIMARY KEY (知识块编号, 锚点));
CREATE TABLE 问答对 (
    编号 text PRIMARY KEY, 场景编码 text NOT NULL, 地区码 text NOT NULL, 知识包版本 text,
    标准问 text NOT NULL, 标准答案 text NOT NULL, 适用范围 text, 标题 text, 快照文件 text);
CREATE TABLE 相似问法 (
    问答对编号 text REFERENCES 问答对(编号), 问法 text, PRIMARY KEY (问答对编号, 问法));
CREATE TABLE 问答对来源 (
    问答对编号 text REFERENCES 问答对(编号), 知识块编号 text, 锚点 text,
    PRIMARY KEY (问答对编号, 知识块编号, 锚点));
CREATE TABLE "Wiki页" (
    编号 text PRIMARY KEY, 场景编码 text NOT NULL, 地区码 text NOT NULL, 知识包版本 text,
    标题 text, 状态 text, 章节 jsonb, 内容 text NOT NULL, 快照文件 text);
CREATE TABLE "Wiki页来源" (
    "Wiki编号" text REFERENCES "Wiki页"(编号), 知识块编号 text, PRIMARY KEY ("Wiki编号", 知识块编号));
CREATE TABLE 共性知识 (
    编号 text PRIMARY KEY, 名称 text, 适用范围 text, 时效 text, 内容 text, 来源锚点 jsonb);
CREATE TABLE 发布记录 (
    序号 int, 时间 text, 地区版本 text, 版本 text, 动作 text, 审核依据 text,
    回滚点 text, 当前有效版本 text, PRIMARY KEY (地区版本, 版本, 动作, 时间));
CREATE TABLE 知识块向量 (
    知识块编号 text PRIMARY KEY REFERENCES 知识块(编号),
    向量 vector(%(dim)s) NOT NULL, 嵌入文本 text, 模型 text, 生成时间 timestamptz DEFAULT now());
CREATE TABLE 问答对向量 (
    问答对编号 text PRIMARY KEY REFERENCES 问答对(编号),
    向量 vector(%(dim)s) NOT NULL, 嵌入文本 text, 模型 text, 生成时间 timestamptz DEFAULT now());
CREATE TABLE "Wiki向量" (
    "Wiki编号" text PRIMARY KEY REFERENCES "Wiki页"(编号),
    向量 vector(%(dim)s) NOT NULL, 嵌入文本 text, 模型 text, 生成时间 timestamptz DEFAULT now());
"""


def jsonl(p: Path):
    with p.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def ensure_database():
    import psycopg2
    conn = psycopg2.connect(dbname="postgres", **PG)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{DB_NAME}" ENCODING \'UTF8\' TEMPLATE template0')
        print(f"已创建独立数据库 {DB_NAME}")
    else:
        print(f"数据库 {DB_NAME} 已存在（将清空重建表）")
    conn.close()


def main(ws: Path, embed=True):
    import psycopg2
    from psycopg2.extras import execute_values
    ex = ws / "80-知识库导出" / "交换态"

    ensure_database()
    conn = psycopg2.connect(dbname=DB_NAME, **PG)
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # 幂等重建：投影可随时从事实源重建
    cur.execute("""SELECT tablename FROM pg_tables WHERE schemaname='public'""")
    for (t,) in cur.fetchall():
        cur.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')
    cur.execute(DDL % {"dim": EMBED_DIM})

    # ---- 知识数据 ----
    docs = list(jsonl(ex / "文档.jsonl"))
    execute_values(cur, "INSERT INTO 文档 VALUES %s",
        [(d["编号"], d["标题"], d["地区"], d["发布机构"], d["文档类型"], d["发布时间"],
          d["生效时间"], d["源文件"], d["内容哈希"], d["完整性"], d["权限范围"],
          d["来源URL"], d["解析文件"], d["解析文件SHA256"]) for d in docs])

    pkgs = list(jsonl(ex / "知识包.jsonl"))
    execute_values(cur, "INSERT INTO 知识包 VALUES %s",
        [(p["包ID"], p["场景编码"], p["地区码"], p["版本"], p["治理档位"], p["发布状态"],
          p["发布动作"], p["时效基准"], p["包清单"], p["包清单SHA256"]) for p in pkgs])

    kcs = list(jsonl(ex / "知识块.jsonl"))
    execute_values(cur, "INSERT INTO 知识块 VALUES %s",
        [(k["编号"], k["场景编码"], k["地区码"], k["知识包版本"], k["类型"], k["标题"],
          k["内容"], k["适用范围"], k["时效说明"], k["快照文件"]) for k in kcs])
    src_rows = {(k["编号"], a) for k in kcs for a in k.get("来源锚点", [])}
    execute_values(cur, "INSERT INTO 知识块来源 VALUES %s", sorted(src_rows))

    qas = list(jsonl(ex / "问答对.jsonl"))
    execute_values(cur, "INSERT INTO 问答对 VALUES %s",
        [(q["编号"], q["场景编码"], q["地区码"], q["知识包版本"], q["标准问"],
          q["标准答案"], q["适用范围"], q["标题"], q["快照文件"]) for q in qas])
    execute_values(cur, "INSERT INTO 相似问法 VALUES %s",
        sorted({(q["编号"], s) for q in qas for s in q.get("相似问法", [])}))
    execute_values(cur, "INSERT INTO 问答对来源 VALUES %s",
        sorted({(q["编号"], kc, a) for q in qas
                for kc in q.get("来源知识块", [])
                for a in (q.get("来源锚点") or ["-"])}))

    wikis = list(jsonl(ex / "Wiki页.jsonl"))
    execute_values(cur, 'INSERT INTO "Wiki页" VALUES %s',
        [(w["编号"], w["场景编码"], w["地区码"], w["知识包版本"], w["标题"], w["状态"],
          json.dumps(w.get("章节", []), ensure_ascii=False), w["内容"], w["快照文件"]) for w in wikis])
    execute_values(cur, 'INSERT INTO "Wiki页来源" VALUES %s',
        sorted({(w["编号"], kc) for w in wikis for kc in w.get("来源知识块", [])}))

    cks = list(jsonl(ex / "共性知识.jsonl"))
    execute_values(cur, "INSERT INTO 共性知识 VALUES %s",
        [(c["编号"], c["名称"], c["适用范围"], c["时效"], c["内容"],
          json.dumps(c.get("来源锚点", []), ensure_ascii=False)) for c in cks])

    rels = list(jsonl(ex / "发布记录.jsonl"))
    execute_values(cur, "INSERT INTO 发布记录 VALUES %s",
        [(r["#"], r["时间"], r["地区版本"], r["版本"], r["动作"], r["审核依据"],
          r["回滚点"], r["当前有效版本"]) for r in rels])
    conn.commit()
    print(f"知识数据加载完成: 文档{len(docs)} 知识包{len(pkgs)} 知识块{len(kcs)} "
          f"问答对{len(qas)} Wiki页{len(wikis)} 共性知识{len(cks)} 发布记录{len(rels)}")

    # ---- 向量数据（pgvector）----
    if embed:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from fastembed import TextEmbedding
        # 优先用工作区内置模型缓存（_models/），离线可用；缺失时再联网下载
        local_cache = ws / "_scripts" / "_models"
        try:
            model = TextEmbedding(EMBED_MODEL, cache_dir=str(local_cache), local_files_only=True)
        except Exception:
            model = TextEmbedding(EMBED_MODEL, cache_dir=str(local_cache))

        def load_vectors(table, key_col, items, text_of):
            pairs = [(it, text_of(it)) for it in items]
            vecs = list(model.embed([t for _, t in pairs]))
            execute_values(cur,
                f'INSERT INTO "{table}" ("{key_col}", 向量, 嵌入文本, 模型) VALUES %s',
                [(it["编号"], list(map(float, v)), t, EMBED_MODEL)
                 for (it, t), v in zip(pairs, vecs)])
            print(f"{table}: {len(pairs)} 条")

        load_vectors("知识块向量", "知识块编号", kcs,
                     lambda k: f"{k['标题']} {k['类型']} {k['内容']}"[:1500])
        load_vectors("问答对向量", "问答对编号", qas,
                     lambda q: f"{q['标准问']} {' '.join(q.get('相似问法', []))}")
        load_vectors("Wiki向量", "Wiki编号", wikis,
                     lambda w: f"{w['标题']} {' '.join(w.get('章节', []))} {w['内容']}"[:1500])
        conn.commit()

    # ---- 验证 ----
    print("\n=== 验证 ===")
    for t in ["文档", "知识包", "知识块", "知识块来源", "问答对", "相似问法",
              "Wiki页", "共性知识", "发布记录", "知识块向量", "问答对向量", "Wiki向量"]:
        cur.execute(f'SELECT count(*) FROM "{t}"')
        print(f"{t}: {cur.fetchone()[0]}")
    conn.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]), embed="--no-embed" not in sys.argv)
