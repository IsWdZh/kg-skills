# -*- coding: utf-8 -*-
"""向量语义检索：对知识块/问答对/Wiki 三类向量做相似度检索。

用法: python demo_vector_search.py <工作区目录> "你的问题"
示例: python demo_vector_search.py 治理工作区 "房子写的是我儿子的名字，公积金能取吗"
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def resolve_models_dir(ws):
    """优先用脚本旁内置的嵌入模型缓存（随技能分发，拷贝即用），其次工作区。"""
    for c in (Path(__file__).resolve().parent / "_models", ws / "_scripts" / "_models"):
        if (c / "fast-bge-small-zh-v1.5").exists():
            return c
    return Path(__file__).resolve().parent / "_models"

PG = dict(host="192.168.108.155", port=5432, user="pgsql", password="Jczh@2026",
          dbname="kg_gjj_trial")
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"


def main(ws: Path, question: str):
    import psycopg2
    from fastembed import TextEmbedding
    model = TextEmbedding(EMBED_MODEL, cache_dir=str(resolve_models_dir(ws)),
                          local_files_only=True)
    vec = list(map(float, list(model.embed([question]))[0]))
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    print(f"问题：{question}\n")

    cur.execute("""SELECT q.编号, q.标准问, left(q.标准答案,80), 1-(v.向量 <=> %s::vector)
        FROM 问答对向量 v JOIN 问答对 q ON q.编号 = v.问答对编号
        ORDER BY v.向量 <=> %s::vector LIMIT 3""", (vec, vec))
    print("【问答对 Top3】")
    for r in cur.fetchall():
        print(f"  {r[3]:.3f}  {r[0]}  {r[1]}\n         答：{r[2]}…")

    cur.execute("""SELECT k.编号, k.类型, left(k.内容,80), 1-(v.向量 <=> %s::vector),
               (SELECT string_agg(锚点, '、') FROM 知识块来源 s WHERE s.知识块编号 = k.编号)
        FROM 知识块向量 v JOIN 知识块 k ON k.编号 = v.知识块编号
        ORDER BY v.向量 <=> %s::vector LIMIT 3""", (vec, vec))
    print("\n【知识块 Top3】")
    for r in cur.fetchall():
        print(f"  {r[3]:.3f}  {r[0]} [{r[1]}] 来源:{r[4]}\n         {r[2]}…")

    cur.execute("""SELECT w.编号, w.标题, 1-(v.向量 <=> %s::vector)
        FROM "Wiki向量" v JOIN "Wiki页" w ON w.编号 = v."Wiki编号"
        ORDER BY v.向量 <=> %s::vector LIMIT 2""", (vec, vec))
    print("\n【Wiki页 Top2】")
    for r in cur.fetchall():
        print(f"  {r[2]:.3f}  {r[0]}  {r[1]}")
    conn.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "退休了公积金怎么提取")
