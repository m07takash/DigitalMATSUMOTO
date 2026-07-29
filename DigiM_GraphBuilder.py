# DigiM_GraphBuilder.py
# ============================================================================
# GraphRAG ingestion batch. Builds <graph_dir>/graph.json from the folder's
# mapping.json (source definitions, 2 lanes) and dictionary.json (aliases /
# seeds / prop_schema).
#
#   # Lane A only (deterministic, no LLM / no API key needed)
#   python3 DigiM_GraphBuilder.py user/common/rag/graph/sample
#
#   # + Lane B free-text extraction via agent_67GraphExtract.json
#   python3 DigiM_GraphBuilder.py user/common/rag/graph/sample --use-llm
#
#   # + node embeddings (for embedding-based entity linking)
#   python3 DigiM_GraphBuilder.py user/common/rag/graph/sample --embed
#
# Rebuild is full (idempotent): node ids derive from canonical names, so a
# re-run over the same sources produces the same graph.
# ============================================================================

import sys
import json

import DigiM_Graph as dmg


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__ or "usage: python3 DigiM_GraphBuilder.py <graph_dir> [--use-llm] [--embed]")
        sys.exit(1)

    graph_dir = args[0]
    report = dmg.build_graph(
        graph_dir,
        use_llm=("--use-llm" in flags),
        embed=("--embed" in flags),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
