import os
import ast
import logging
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.cluster import KMeans, DBSCAN, AgglomerativeClustering
import chromadb
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Execute as dme
import DigiM_Util as dmu

logger = logging.getLogger(__name__)

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
rag_folder_db_path = system_setting_dict["RAG_FOLDER_DB"]

# エージェントのシンプルな実行
def genLLMAgentSimple(service_info, user_info, session_id, session_name, agent_file, model_type="LLM", sub_seq=1, query="", import_contents=[], situation={}, overwrite_items={}, add_knowledge=[], prompt_temp_cd="No Template", execution={}, seq_limit="", sub_seq_limit=""):
    # overwrite適用後のmodel_nameを取得
    agent = dma.DigiM_Agent(agent_file)
    if overwrite_items:
        dmu.update_dict(agent.agent, overwrite_items)
        agent.set_property(agent.agent)
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]

    # 実行の設定
    execution = {}
    execution["CONTENTS_SAVE"] = False
    execution["MEMORY_SAVE"] = False
    execution["STREAM_MODE"] = True
    execution["SAVE_DIGEST"] = False

    # LLM実行
    response = ""
    for response_service_info, response_user_info, response_chunk, export_contents, knowledge_ref in dme.DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type, sub_seq, query, import_contents, situation=situation, overwrite_items=overwrite_items, add_knowledge=add_knowledge, prompt_temp_cd=prompt_temp_cd, execution=execution, seq_limit=seq_limit, sub_seq_limit=sub_seq_limit):
        if response_chunk and not str(response_chunk).startswith("[STATUS]"):
            response += response_chunk

    return response_service_info, response_user_info, response, model_name, export_contents, knowledge_ref

# 知識活用性のグラフを作成
def create_similarity_plot_file(file_title, analytics_file_path, rag_name, group):
    fig, ax = plt.subplots(figsize=(24, 8))
    bar_height = 0.4  # Adjust bar height to separate the bars
    y_positions = range(len(group))

    ax.barh([y - bar_height / 2 for y in y_positions], group['similarity_Q'], height=bar_height, color=group["q_colors"], label='similarity_Q')
    ax.barh([y + bar_height / 2 for y in y_positions], group['similarity_A'], height=bar_height, color='orange', label='similarity_A')

    ax.set_xlabel('Similarity Distance', fontsize=12)
    ax.set_ylabel('Title', fontsize=12)
    ax.set_title(f'{rag_name} - Similarity_Q vs Similarity_A (Sorted by Similarity_Q Desc)', fontsize=14)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(group['title'], fontsize=8)
    ax.legend()

    similarity_plot_file = f"{file_title}_KUtilPlot_{rag_name}.png"    
    filename = str(Path(analytics_file_path) / similarity_plot_file)
    plt.savefig(filename)
    plt.close(fig)

    return similarity_plot_file

# PCA/TSNEを算出してプロットしたファイルを作成
def plot_rag_scatter(file_title, analytics_file_path, rag_name, rag_data_list, mode={"method":"PCA", "params":{}}, category_map={}):
    scatter_plot_file_category = ""
    scatter_plot_file_ref = ""
    scatter_plot_file_csv = ""

    df = pd.DataFrame(rag_data_list)
    vectors = np.array(df["vector_data_value_text"].tolist(), dtype=np.float32)

    method = mode["method"]
    params = mode["params"]
    xcol, ycol = "X1", "X2"

    # タイトルに付ける説明率文字列
    pca_info_text = ""

    if method == "PCA":
        model = PCA(n_components=2)
        emb = model.fit_transform(vectors)

        # 第1・第2主成分の説明率と累積説明率
        pc1_ratio = model.explained_variance_ratio_[0]
        pc2_ratio = model.explained_variance_ratio_[1]
        cumulative_ratio = pc1_ratio + pc2_ratio

        pca_info_text = (
            f"\nPC1: {pc1_ratio:.2%}, "
            f"PC2: {pc2_ratio:.2%}, "
            f"PC1+PC2 Coverage: {cumulative_ratio:.2%}"
        )

    elif method == "t-SNE":
        n = len(df)
        perplexity = min(params["perplexity"], max(2, n - 1))
        random_state = 0

        model = TSNE(
            n_components=2,
            perplexity=perplexity,
            init="pca",
            learning_rate="auto",
            random_state=random_state,
        )
        emb = model.fit_transform(vectors)
    else:
        raise ValueError(f"Unknown method: {method} (use 'PCA' or 't-SNE')")

    df[xcol] = emb[:, 0]
    df[ycol] = emb[:, 1]

    # --- リファレンス散布図 ---
    scatter_plot_file_ref = f"{file_title}_ScatterRefPlot({method})_{rag_name}.png"
    scatter_plot_filename_ref = str(Path(analytics_file_path) / scatter_plot_file_ref)

    fig_ref, ax_ref = plt.subplots(figsize=(10, 8))
    ax_ref.scatter(df[xcol], df[ycol], c=df["ref_color"], alpha=0.7)
    ax_ref.set_title(f"{method} Analysis(Ref): {rag_name}{pca_info_text}")
    ax_ref.grid(True)
    fig_ref.savefig(scatter_plot_filename_ref, dpi=150, bbox_inches="tight")
    plt.close(fig_ref)

    # カテゴリーの散布図
    if "category_color" in df.columns:
        scatter_plot_file_category = f"{file_title}_ScatterCategoryPlot({method})_{rag_name}.png"
        scatter_plot_filename_category = str(Path(analytics_file_path) / scatter_plot_file_category)

        fig_cat, ax_cat = plt.subplots(figsize=(10, 8))
        ax_cat.scatter(df[xcol], df[ycol], c=df["category_color"], alpha=0.7)
        ax_cat.set_title(f"{method} Analysis(Category): {rag_name}{pca_info_text}")
        ax_cat.grid(True)

        if category_map:
            category_handles = [
                plt.Line2D([0], [0], marker="o", color="w", label=key, markersize=10, markerfacecolor=color)
                for key, color in category_map.items()
            ]
            category_handles.append(
                plt.Line2D([0], [0], marker="o", color="w", label="その他", markersize=10, markerfacecolor="gray")
            )
            ax_cat.legend(handles=category_handles, loc="upper left", bbox_to_anchor=(1, 1), title="カテゴリ")

        fig_cat.savefig(scatter_plot_filename_category, dpi=150, bbox_inches="tight")
        plt.close(fig_cat)

    # 散布図にプロットされるデータ(CSV)
    if "category_color" in df.columns:
        display_items = ["id", "title", "create_date", xcol, ycol, "category_color", "category_sum", "category", "db", "value_text"]
    else:
        display_items = ["id", "title", "create_date", xcol, ycol, "value_text"]

    existing_items = [c for c in display_items if c in df.columns]
    df_csv = df.loc[df["ref_color"] != "gray", existing_items].sort_values(by=[xcol, ycol], ascending=[True, True])

    scatter_plot_file_csv = f"{file_title}_ScatterData({method})_{rag_name}.csv"
    scatter_plot_filename_csv = str(Path(analytics_file_path) / scatter_plot_file_csv)
    df_csv.to_csv(scatter_plot_filename_csv, index=True, encoding="utf-8-sig")

    return scatter_plot_file_category, scatter_plot_file_ref, scatter_plot_file_csv

# RAG Explorer用: ベクトルデータの次元削減（散布図座標を返す）
def reduce_dimensions(df, vector_col="vector_data_value_text", method="PCA", params={}):
    """DataFrameのベクトルカラムを2次元に削減し、X1/X2カラムを追加して返す。infoテキストも返す。"""
    vectors_raw = df[vector_col].tolist()
    # 文字列の場合はパースする
    vectors = []
    for v in vectors_raw:
        if isinstance(v, str):
            vectors.append(ast.literal_eval(v))
        elif isinstance(v, list):
            vectors.append(v)
        else:
            vectors.append(v)
    vectors = np.array(vectors, dtype=np.float32)

    info_text = ""
    if method == "PCA":
        model = PCA(n_components=2)
        emb = model.fit_transform(vectors)
        pc1 = model.explained_variance_ratio_[0]
        pc2 = model.explained_variance_ratio_[1]
        info_text = f"PC1: {pc1:.2%}, PC2: {pc2:.2%}, Coverage: {pc1+pc2:.2%}"
    elif method == "t-SNE":
        n = len(df)
        perplexity = min(params.get("perplexity", 30), max(2, n - 1))
        model = TSNE(n_components=2, perplexity=perplexity, init="pca", learning_rate="auto", random_state=0)
        emb = model.fit_transform(vectors)
        info_text = f"t-SNE (perplexity={perplexity})"
    else:
        raise ValueError(f"Unknown method: {method}")

    df_result = df.copy()
    df_result["X1"] = emb[:, 0]
    df_result["X2"] = emb[:, 1]
    return df_result, info_text

# RAG Explorer用: DBSCANのeps自動推定（k-距離法）
def estimate_dbscan_eps(df, k=5):
    """X1/X2座標のk番目近傍距離から最適なepsを推定する"""
    from sklearn.neighbors import NearestNeighbors
    coords = df[["X1", "X2"]].values
    k = min(k, len(coords) - 1)
    nn = NearestNeighbors(n_neighbors=k)
    nn.fit(coords)
    distances, _ = nn.kneighbors(coords)
    k_distances = np.sort(distances[:, -1])
    # 2次差分（加速度）が最大の点 = 「急に距離が増える点」
    if len(k_distances) < 3:
        return float(np.median(k_distances))
    diffs = np.diff(k_distances)
    diffs2 = np.diff(diffs)
    if len(diffs2) == 0:
        return float(np.median(k_distances))
    elbow_idx = np.argmax(diffs2) + 2
    eps = float(k_distances[min(elbow_idx, len(k_distances) - 1)])
    # 最低値を保証（0に近すぎると全ノイズになる）
    eps = max(eps, float(np.percentile(k_distances, 10)))
    return round(eps, 2)

# RAG Explorer用: クラスタリング実行
def apply_clustering(df, method="K-Means", params={}):
    """X1/X2座標を使ってクラスタリングし、Cluster列を追加して返す。info文字列も返す。"""
    coords = df[["X1", "X2"]].values
    info = ""

    if method == "K-Means":
        n_clusters = params.get("n_clusters", 5)
        model = KMeans(n_clusters=n_clusters, random_state=0, n_init=10)
        labels = model.fit_predict(coords)
        info = f"K-Means (k={n_clusters})"
    elif method == "DBSCAN":
        eps = params.get("eps")
        min_samples = params.get("min_samples", 5)
        if eps is None or eps <= 0:
            eps = estimate_dbscan_eps(df, k=min_samples)
        model = DBSCAN(eps=eps, min_samples=min_samples)
        labels = model.fit_predict(coords)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_noise = (labels == -1).sum()
        info = f"DBSCAN (eps={eps}, min_samples={min_samples}) → {n_clusters}クラスタ, ノイズ{n_noise}件"
    elif method == "Hierarchical":
        n_clusters = params.get("n_clusters", 5)
        model = AgglomerativeClustering(n_clusters=n_clusters)
        labels = model.fit_predict(coords)
        info = f"Hierarchical (k={n_clusters})"
    else:
        raise ValueError(f"Unknown method: {method}")

    df_result = df.copy()
    df_result["Cluster"] = labels
    return df_result, info

# クラスターごとのサマリーを生成（LLM解説用コンテキスト）
def build_cluster_summary(df, text_col="value_text", max_samples=5):
    """クラスターごとのサンプルデータをテキストにまとめる"""
    summary_lines = []
    for cluster_id in sorted(df["Cluster"].unique()):
        cluster_df = df[df["Cluster"] == cluster_id]
        label = f"Cluster {cluster_id}" if cluster_id >= 0 else "ノイズ（未分類）"
        summary_lines.append(f"\n【{label}】({len(cluster_df)}件)")
        if "category" in cluster_df.columns:
            cat_dist = cluster_df["category"].value_counts().head(5).to_dict()
            summary_lines.append("  カテゴリ分布: " + ", ".join(f"{k}:{v}件" for k, v in cat_dist.items()))
        # サンプルテキスト
        _col = text_col if text_col in cluster_df.columns else "title" if "title" in cluster_df.columns else None
        if _col:
            samples = cluster_df[_col].dropna().head(max_samples).tolist()
            for s in samples:
                summary_lines.append(f"  - {str(s)[:120]}")
    return "\n".join(summary_lines)

# RAG Explorer用: 感度分析（入力テキストに対する全チャンクのコサイン距離+期間ボーナス）
def sensitivity_analysis(df, query_text, vector_col="vector_data_value_text", top_n=20,
                         date_from=None, date_to=None, date_bonus=0.0):
    """入力テキストをembed→全チャンクとcosine距離を計算→期間ボーナス適用→スコアでランキング"""
    query_vec = dmu.embed_text(query_text.replace("\n", ""))

    distances = []
    for _, row in df.iterrows():
        vec = row[vector_col]
        if isinstance(vec, str):
            vec = ast.literal_eval(vec)
        dist = dmu.calculate_cosine_distance(query_vec, vec)
        distances.append(dist)

    df_result = df.copy()
    df_result["cos_distance"] = distances

    # 期間ボーナスの適用
    df_result["bonus_applied"] = False
    if date_from and date_to and date_bonus > 0 and "create_date" in df_result.columns:
        _dates = pd.to_datetime(df_result["create_date"], errors="coerce")
        _in_range = (_dates >= pd.Timestamp(date_from)) & (_dates <= pd.Timestamp(date_to) + pd.Timedelta(days=1))
        df_result.loc[_in_range, "bonus_applied"] = True

    # スコア計算: ボーナス対象はcos_distance * bonus（値が小さいほど上位）
    df_result["score"] = df_result.apply(
        lambda r: r["cos_distance"] * date_bonus if r["bonus_applied"] else r["cos_distance"], axis=1)
    df_result = df_result.sort_values("score", ascending=True)

    # 表示用カラム（ベクトル除外）
    _exclude = [c for c in df_result.columns if "vector_data" in c]
    df_display = df_result.drop(columns=_exclude, errors="ignore")

    # クラスター別の平均スコア（Cluster列がある場合）
    cluster_stats = None
    if "Cluster" in df_result.columns:
        cluster_stats = df_result.groupby("Cluster")["score"].agg(["mean", "min", "count"]).reset_index()
        cluster_stats.columns = ["Cluster", "avg_score", "min_score", "count"]
        cluster_stats = cluster_stats.sort_values("avg_score", ascending=True)

    return df_display.head(top_n), cluster_stats

# RAG Explorer用: 時系列分析（期間ごとのキーワード+カテゴリ推移）
def temporal_analysis(df, period="month", top_n_keywords=10, text_col="value_text"):
    """create_dateで期間集約し、TF-IDFキーワード+カテゴリ構成を返す"""
    if "create_date" not in df.columns or text_col not in df.columns:
        return None, None, ""

    df_work = df.copy()
    df_work["_date"] = pd.to_datetime(df_work["create_date"], errors="coerce")
    df_work = df_work.dropna(subset=["_date"])
    if df_work.empty:
        return None, None, ""

    # 期間ラベル生成
    if period == "year":
        df_work["_period"] = df_work["_date"].dt.strftime("%Y")
    elif period == "quarter":
        df_work["_period"] = df_work["_date"].dt.to_period("Q").astype(str)
    else:
        df_work["_period"] = df_work["_date"].dt.strftime("%Y-%m")
    periods = sorted(df_work["_period"].unique())

    # カテゴリ推移（カテゴリがある場合）
    category_pivot = None
    if "category" in df_work.columns:
        cat_cross = df_work.groupby(["_period", "category"]).size().reset_index(name="count")
        category_pivot = cat_cross.pivot_table(index="_period", columns="category", values="count", fill_value=0)
        category_pivot = category_pivot.reindex(periods)

    # 期間ごとのTF-IDFキーワード抽出
    period_texts = df_work.groupby("_period")[text_col].apply(lambda x: " ".join(x.dropna().astype(str))).to_dict()
    all_texts = list(period_texts.values())
    if not all_texts or all(t.strip() == "" for t in all_texts):
        return category_pivot, None, ""

    # 名詞のみ抽出 + ストップワードで一般的な語を除外
    _stop_words = [
        # 形式名詞・代名詞
        "こと", "もの", "ため", "それ", "これ", "あれ", "ここ", "そこ", "どこ",
        "よう", "ところ", "とき", "なか", "うち", "ほう", "わけ", "はず", "つもり",
        "ほか", "まま", "あと", "とおり", "せい", "おかげ", "くせ",
        # 一般的すぎる名詞
        "人", "自分", "相手", "方", "さん", "たち", "みんな", "皆",
        "今", "前", "後", "上", "下", "中", "内", "外", "間", "先", "次", "最初", "最後",
        "場合", "必要", "可能", "重要", "大切", "意味", "問題", "結果", "状況", "状態",
        "全体", "部分", "一部", "一つ", "一方", "両方", "以上", "以下", "程度",
        "感じ", "形", "点", "面", "側", "度", "回", "件", "個", "本", "種", "数",
        "目", "手", "力", "気", "声", "話", "言葉", "名前", "時間", "日", "月", "年",
        "的", "性", "化", "用", "系", "式", "型", "版", "別", "向け",
        # 動作・状態の名詞化
        "対応", "実行", "実現", "実施", "実装", "利用", "活用", "使用", "導入", "設定",
        "確認", "理解", "認識", "判断", "検討", "議論", "説明", "表現", "表示", "提供",
        "作成", "生成", "構築", "開発", "設計", "管理", "運用", "処理", "変更", "更新",
        "追加", "削除", "取得", "選択", "指定", "定義", "評価", "分析", "比較", "改善",
        "影響", "関係", "関連", "連携", "統合", "機能", "役割", "目的", "効果", "価値",
        "情報", "データ", "内容", "対象", "範囲", "条件", "基準", "観点", "視点", "傾向",
        # 接尾辞的な語
        "こちら", "そちら", "あちら", "どちら",
    ]
    vectorizer = dmu.fit_tfidf(all_texts, stop_words=_stop_words, grammer=('名詞',))
    keyword_rows = []
    for p in periods:
        text = period_texts.get(p, "")
        if not text.strip():
            keyword_rows.append({"period": p, "count": 0, "keywords": ""})
            continue
        count = len(df_work[df_work["_period"] == p])
        _, tfidf_topN, tfidf_str = dmu.get_tfidf_list(text, vectorizer, top_n_keywords)
        keywords = ", ".join([w for w, s in tfidf_topN])
        keyword_rows.append({"period": p, "count": count, "keywords": keywords})
    keyword_df = pd.DataFrame(keyword_rows)

    # LLM解説用サマリー
    summary_lines = [f"期間: {periods[0]}〜{periods[-1]} ({len(periods)}期間, {len(df_work)}件)"]
    for row in keyword_rows:
        if row["keywords"]:
            summary_lines.append(f"  {row['period']} ({row['count']}件): {row['keywords']}")
    summary_text = "\n".join(summary_lines)

    return category_pivot, keyword_df, summary_text

# 知識参照度と知識活用度の分析
def analytics_knowledge(agent_file, ref_timestamp, title, reference, analytics_file_path, ak_mode="Default", dim_mode={"method":"PCA", "params":{}}):
#    end_date_str = datetime.strptime(ref_timestamp, "%Y-%m-%d %H:%M:%S.%f").strftime("%Y-%m-%d")
    end_date_str = dmu.parse_date(ref_timestamp).strftime("%Y-%m-%d")
    df = pd.DataFrame(reference)

    # 正規化
    if ak_mode == "Norm(All)":
        max_val_Q = df["similarity_Q"].max()
        max_val_A = df["similarity_A"].max()
        df["similarity_Q"] = df["similarity_Q"]/max_val_Q
        df["similarity_A"] = df["similarity_A"]/max_val_A
    elif ak_mode == "Norm(Group)":
        df["similarity_Q"] = df["similarity_Q"] / df.groupby("rag")["similarity_Q"].transform("max")
        df["similarity_A"] = df["similarity_A"] / df.groupby("rag")["similarity_A"].transform("max")

    df['knowledge_utility'] = round(df['similarity_Q'] - df['similarity_A'], 3)
    file_title = dmu.sanitize_filename(title[:30])

    # エージェントのKNOWLEDGE→BOOKの定義順を取得
    agent = dma.DigiM_Agent(agent_file)
    rag_order = [k.get("NAME", "") for k in agent.knowledge] + [b.get("RAG_NAME", "") for b in agent.book]

    # similarity_Qの統計量を算出
    similarity_Q_stats = df.groupby('rag')['similarity_Q'].agg([
        ('min', 'min'),
        ('mean', 'mean'),
        ('median', 'median'),
        ('max', 'max'),
        ('variance', lambda x: np.var(x, ddof=1))
    ]).reset_index()

    # similarity_Aの統計量を算出
    similarity_A_stats = df.groupby('rag')['similarity_A'].agg([
        ('min', 'min'),
        ('mean', 'mean'),
        ('median', 'median'),
        ('max', 'max'),
        ('variance', lambda x: np.var(x, ddof=1))
    ]).reset_index()

    # 知識活用性の統計量を算出
    knowledge_utility_stats = df.groupby('rag')['knowledge_utility'].agg([
        ('min', 'min'),
        ('mean', 'mean'),
        ('median', 'median'),
        ('max', 'max'),
        ('variance', lambda x: np.var(x, ddof=1))
    ]).reset_index()

    # RAGごとの知識活用性（Q最小値-A最小値）を算出
    knowledge_utility_stats_dict = dict(zip(similarity_Q_stats['rag'], knowledge_utility_stats['max']))

    # 出力用に辞書形式に変換（エージェントのKNOWLEDGE定義順で並べ替え）
    def _order_dict_by_rag(d):
        """辞書をrag_orderの順序で並べ替える"""
        ordered = {}
        for rn in rag_order:
            # キーが直接rag名の場合（similarity_rank, utility等）
            if rn in d:
                ordered[rn] = d[rn]
            else:
                # キーがint indexで値にragフィールドがある場合（stats系）
                for k, v in d.items():
                    if isinstance(v, dict) and v.get('rag') == rn and k not in ordered.values():
                        ordered[k] = v
                        break
        for k, v in d.items():
            if k not in ordered:
                ordered[k] = v
        return ordered

    similarity_Q_stats_dict = _order_dict_by_rag(similarity_Q_stats.to_dict(orient='index'))
    similarity_A_stats_dict = _order_dict_by_rag(similarity_A_stats.to_dict(orient='index'))
    similarity_utility_dict = _order_dict_by_rag(knowledge_utility_stats_dict)
    similarity_rank_raw = (df.sort_values(['rag', 'similarity_Q'], ascending=[True, True]).groupby('rag')[['DB', 'ID', 'title', 'similarity_Q', 'similarity_A','knowledge_utility', 'QUERY_SEQ', 'QUERY_MODE']].apply(lambda x: x.to_dict(orient='records')).to_dict())
    similarity_rank = _order_dict_by_rag(similarity_rank_raw)

    # フォルダがなければ作成
    if not os.path.exists(analytics_file_path):
        os.makedirs(analytics_file_path, exist_ok=True)

    # テキストファイルの保存
    similarity_Q_stats_file = f"{file_title}_KUtilStats(Q).txt"
    similarity_A_stats_file = f"{file_title}_KUtilStats(A).txt"
    similarity_utility_file = f"{file_title}_KUtilStats(A-Q).txt"
    similarity_rank_file = f"{file_title}_KUtilRanking.txt"

    with open(Path(analytics_file_path) / similarity_Q_stats_file, "w", encoding="utf-8") as file:
        file.write(str(similarity_Q_stats_dict))
    with open(Path(analytics_file_path) / similarity_A_stats_file, "w", encoding="utf-8") as file:
        file.write(str(similarity_A_stats_dict))
    with open(Path(analytics_file_path) / similarity_utility_file, "w", encoding="utf-8") as file:
        file.write(str(similarity_utility_dict))
    with open(Path(analytics_file_path) / similarity_rank_file, "w", encoding="utf-8") as file:
        file.write(str(similarity_rank))

    # Sort data by similarity_Q in descending order within each rag
    sorted_plot_data = df.sort_values(by=['rag', 'similarity_Q'], ascending=[True, False])

    # フォントを設定
    rcParams['font.family'] = 'Noto Sans CJK JP'

    # 保存用のファイルリスト
    scatter_plot_category_files = []
    scatter_plot_ref_files = []
    scatter_plot_csv_files = []
    similarity_plot_files = []

    category_map_file = "category_map.json"
    category_map_json = dmu.read_json_file(category_map_file, mst_folder_path)
    category_map = {}
    if "CategoryColor" in category_map_json:
        category_map = category_map_json["CategoryColor"]

    # KnowledgeのRAGデータ毎に処理（エージェントのKNOWLEDGE→BOOKの定義順で出力）
    db_client = dmc.get_chroma_client()
    knowledge_map = {k.get("RAG_NAME"): k for k in agent.knowledge}
    color_map = {
        "1": ("blue", "lightskyblue"),
        "2": ("navy", "cornflowerblue"),
        "default": ("deepskyblue", "powderblue"),
    }
    cat_category = category_map_json.get("Category", {})
    cat_color = category_map_json.get("CategoryColor", {})

    grouped = dict(list(sorted_plot_data.groupby('rag')))
    ordered_groups = [(name, grouped[name]) for name in rag_order if name in grouped]
    ordered_groups += [(name, grp) for name, grp in grouped.items() if name not in rag_order]

    # 必要なコレクションデータを並列で事前取得
    _collections_needed = {}
    for rag_name, group in ordered_groups:
        knowledge = knowledge_map.get(rag_name)
        if knowledge:
            for rd in knowledge["DATA"]:
                if rd["DATA_TYPE"] == "DB":
                    _collections_needed[rd["DATA_NAME"]] = None

    def _fetch_collection(col_name):
        try:
            col = db_client.get_collection(col_name)
            return col_name, col.get(include=["metadatas", "embeddings"])
        except Exception:
            logger.warning(f"[SKIP] ChromaDB collection not found: {col_name}")
            return col_name, None

    with ThreadPoolExecutor(max_workers=min(4, len(_collections_needed) or 1)) as executor:
        for col_name, col_data in executor.map(lambda n: _fetch_collection(n), _collections_needed.keys()):
            _collections_needed[col_name] = col_data

    for rag_name, group in ordered_groups:
        group["q_colors"] = [
            color_map.get(seq, color_map["default"])[0 if mode == "NORMAL" else 1]
            for seq, mode in zip(group["QUERY_SEQ"], group["QUERY_MODE"])
        ]

        knowledge = knowledge_map.get(rag_name)
        if knowledge:
            id_color_map = dict(zip(group["ID"], group["q_colors"]))

            rag_data_list = []
            for rag_data in knowledge["DATA"]:
                if rag_data["DATA_TYPE"] != "DB":
                    continue
                rag_data_db = _collections_needed.get(rag_data["DATA_NAME"])
                if not rag_data_db:
                    continue

                ids = rag_data_db["ids"]
                metas = rag_data_db["metadatas"]
                embeddings = rag_data_db["embeddings"]

                for i in range(len(ids)):
                    meta = metas[i]
                    if meta.get("create_date", "")[:10] > end_date_str[:10]:
                        continue
                    v = {"id": ids[i]}
                    v |= meta
                    vec_str = v.get("vector_data_value_text", "")
                    v["vector_data_value_text"] = ast.literal_eval(vec_str) if isinstance(vec_str, str) else vec_str
                    v["vector_data_key_text"] = embeddings[i] if isinstance(embeddings[i], list) else embeddings[i].tolist()
                    v["ref_color"] = id_color_map.get(ids[i], "gray")
                    if "category" in v and cat_category:
                        v["category_sum"] = cat_category.get(v["category"], "その他")
                        v["category_color"] = cat_color.get(v["category_sum"], "gray")
                    rag_data_list.append(v)

            if rag_data_list:
                scatter_plot_category_file, scatter_plot_ref_file, scatter_plot_csv_file = plot_rag_scatter(file_title, analytics_file_path, rag_name, rag_data_list, dim_mode, category_map)
                if scatter_plot_category_file:
                    scatter_plot_category_files.append(scatter_plot_category_file)
                if scatter_plot_ref_file:
                    scatter_plot_ref_files.append(scatter_plot_ref_file)
                if scatter_plot_csv_file:
                    scatter_plot_csv_files.append(scatter_plot_csv_file)

        similarity_plot_files.append(create_similarity_plot_file(file_title, analytics_file_path, rag_name, group))

    result = {
        "similarity_Q_stats": similarity_Q_stats_dict,
        "similarity_A_stats": similarity_A_stats_dict,
        "similarity_utility": similarity_utility_dict,
        "similarity_rank": similarity_rank,
        "files": {
            "similarity_Q_stats_file": similarity_Q_stats_file,
            "similarity_A_stats_file": similarity_A_stats_file,
            "similarity_utility_file": similarity_utility_file,
            "similarity_rank_file": similarity_rank_file
            },
        "image_files": {
            "scatter_plot_file_category": scatter_plot_category_files,
            "scatter_plot_file_ref": scatter_plot_ref_files,
            "scatter_plot_file_csv": scatter_plot_csv_files,
            "similarity_plot_file": similarity_plot_files
            }
    }

    return result
