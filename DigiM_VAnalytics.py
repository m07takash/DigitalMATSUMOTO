import os
import ast
import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib import rcParams
from sklearn.decomposition import PCA
import chromadb

import DigiM_Agent as dma
import DigiM_Execute as dme
import DigiM_Util as dmu

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
rag_folder_db_path = system_setting_dict["RAG_FOLDER_DB"]

# エージェントのシンプルな実行
def genLLMAgentSimple(service_info, user_info, session_id, session_name, agent_file, model_type="LLM", sub_seq=1, query="", import_contents=[], situation={}, overwrite_items={}, add_knowledge=[], prompt_temp_cd="No Template", execution={}, seq_limit="", sub_seq_limit=""):
    agent = dma.DigiM_Agent(agent_file)
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]

    # 実行の設定
    execution = {}
    execution["CONTENTS_SAVE"] = False
    execution["MEMORY_SAVE"] = False
    execution["STREAM_MODE"] = False
    execution["SAVE_DIGEST"] = False

    # LLM実行
    response = ""
    for response_service_info, response_user_info, response_chunk, export_contents, knowledge_ref in dme.DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type, sub_seq, query, import_contents, situation=situation, overwrite_items=overwrite_items, add_knowledge=add_knowledge, prompt_temp_cd=prompt_temp_cd, execution=execution, seq_limit=seq_limit, sub_seq_limit=sub_seq_limit):
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
    filename = analytics_file_path + similarity_plot_file
    plt.savefig(filename)
    plt.close(fig)

    return similarity_plot_file

# PCAを算出してプロットしたファイルを作成
def plot_rag_scatter(file_title, analytics_file_path, rag_name, rag_data_list, category_map):
    scatter_plot_file_category = ""
    scatter_plot_file_ref = ""
    scatter_plot_file_csv = ""
    
    df = pd.DataFrame(rag_data_list) 
    df['vec_value_text_pca'] = df['vector_data_value_text'].apply(np.array)
    vectors = np.vstack(df['vec_value_text_pca'].to_numpy())
    pca = PCA(n_components=2)
    principal_components = pca.fit_transform(vectors)
    df['PC1'] = principal_components[:, 0]
    df['PC2'] = principal_components[:, 1]

    # リファレンスの散布図
    scatter_plot_file_ref = f"{file_title}_ScatterRefPlot_{rag_name}.png"
    scatter_plot_filename_ref = analytics_file_path + scatter_plot_file_ref
    plt.figure(figsize=(10, 8))
    plt.scatter(df['PC1'], df['PC2'], c=df['ref_color'], alpha=0.7)
    plt.title(f'PCA Analysis(Ref): {rag_name}')
    plt.grid(True)
    plt.savefig(scatter_plot_filename_ref, dpi=300, bbox_inches='tight')
    plt.show()

    # カテゴリーの散布図
    if 'category_color' in df.columns:
        scatter_plot_file_category = f"{file_title}_ScatterCategoryPlot_{rag_name}.png"
        scatter_plot_filename_category = analytics_file_path + scatter_plot_file_category
        plt.figure(figsize=(10, 8))
        plt.scatter(df['PC1'], df['PC2'], c=df['category_color'], alpha=0.7)
        plt.title(f'PCA Analysis(Category): {rag_name}')
        plt.grid(True)
        if category_map:
            category_handles = [plt.Line2D([0], [0], marker='o', color='w', label=key, markersize=10, markerfacecolor=color)
                                for key, color in category_map.items()]
            category_handles.append(plt.Line2D([0], [0], marker='o', color='w', label='その他', markersize=10, markerfacecolor='gray'))
            plt.legend(handles=category_handles, loc='upper left', bbox_to_anchor=(1, 1), title="カテゴリ")
        plt.savefig(scatter_plot_filename_category, dpi=300, bbox_inches='tight')
        plt.show()
    
    if 'category_color' in df.columns:
        display_items = ["id", "title", "create_date", "PC1", "PC2", "category_color", "category_sum", "category", "db", "value_text"]
    else:
        display_items = ["id", "title", "create_date", "PC1", "PC2", "value_text"]
    df_csv = (df.loc[df["ref_color"] != "gray", display_items].sort_values(by=["PC1", "PC2"], ascending=[True, True]))
    scatter_plot_file_csv = f"{file_title}_ScatterData_{rag_name}.csv"
    scatter_plot_filename_csv = analytics_file_path + scatter_plot_file_csv
    df_csv.to_csv(scatter_plot_filename_csv, index=True, encoding='utf-8-sig')

    return scatter_plot_file_category, scatter_plot_file_ref, scatter_plot_file_csv


# 知識参照度と知識活用度の分析
def analytics_knowledge(agent_file, ref_timestamp, title, reference, analytics_file_path, ak_mode="Default"):
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
    
    # 出力用に辞書形式に変換
    similarity_Q_stats_dict = similarity_Q_stats.to_dict(orient='index') 
    similarity_A_stats_dict = similarity_A_stats.to_dict(orient='index') 
    similarity_utility_dict = knowledge_utility_stats_dict
    similarity_rank = (df.sort_values(['rag', 'similarity_Q'], ascending=[True, True]).groupby('rag')[['DB', 'ID', 'title', 'similarity_Q', 'similarity_A','knowledge_utility', 'QUERY_SEQ', 'QUERY_MODE']].apply(lambda x: x.to_dict(orient='records')).to_dict())

    # フォルダがなければ作成
    if not os.path.exists(analytics_file_path):
        os.makedirs(analytics_file_path, exist_ok=True)

    # テキストファイルの保存
    similarity_Q_stats_file = f"{file_title}_KUtilStats(Q).txt"
    similarity_A_stats_file = f"{file_title}_KUtilStats(A).txt"
    similarity_utility_file = f"{file_title}_KUtilStats(A-Q).txt"
    similarity_rank_file = f"{file_title}_KUtilRanking.txt"

    with open(analytics_file_path+similarity_Q_stats_file, "w", encoding="utf-8") as file:
        file.write(str(similarity_Q_stats_dict))
    with open(analytics_file_path+similarity_A_stats_file, "w", encoding="utf-8") as file:
        file.write(str(similarity_A_stats_dict))
    with open(analytics_file_path+similarity_utility_file, "w", encoding="utf-8") as file:
        file.write(str(similarity_utility_dict))
    with open(analytics_file_path+similarity_rank_file, "w", encoding="utf-8") as file:
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

    # KnowledgeのRAGデータ毎に処理
    agent = dma.DigiM_Agent(agent_file)
    for rag_name, group in sorted_plot_data.groupby('rag'):
        color_map = {
            "1": ("blue", "lightskyblue"),
            "2": ("navy", "cornflowerblue"),
            "default": ("deepskyblue", "powderblue")
        }

        group["q_colors"] = [
            (
                color_map.get(seq, color_map["default"])[0]
                if mode == "NORMAL"
                else color_map.get(seq, color_map["default"])[1]
            )
            for seq, mode in zip(group["QUERY_SEQ"], group["QUERY_MODE"])
        ]

        for knowledge in agent.knowledge:
            if knowledge.get("RAG_NAME") == rag_name:
                rag_data_list = []
                for rag_data in knowledge["DATA"]:
                    if rag_data["DATA_TYPE"] == "DB":
                        db_client = chromadb.PersistentClient(path=rag_folder_db_path)
                        try:
                            collection = db_client.get_collection(rag_data["DATA_NAME"])
                        except Exception as e:
                            print(f"[SKIP] ChromaDB collection not found: {rag_data['DATA_NAME']}")
                            continue
                    
                        rag_data_db = collection.get(include=["metadatas", "embeddings"])
                        for i in range(len(rag_data_db["ids"])):
                            v = {}
                            v["id"] = rag_data_db["ids"][i]
                            v |= rag_data_db["metadatas"][i]
                            v["vector_data_value_text"] = ast.literal_eval(v["vector_data_value_text"])
                            v["vector_data_key_text"] = rag_data_db["embeddings"][i].tolist()
                            v["ref_color"] = (group.loc[group["ID"] == v["id"], "q_colors"].iloc[0] if (group["ID"] == v["id"]).any() else "gray")
                            if v["create_date"][:10] <= end_date_str[:10]:
                                if 'category' in v:
                                    if category_map_json:
                                        v["category_sum"] = category_map_json["Category"].get(v["category"], "その他")
                                        if v["category_sum"] in category_map_json["CategoryColor"]:
                                            v["category_color"] = category_map_json["CategoryColor"][v["category_sum"]]
                                        else:
                                            v["category_color"] = "gray"                        
                                rag_data_list.append(v)
                    
                if rag_data_list:
                    scatter_plot_category_file, scatter_plot_ref_file, scatter_plot_csv_file = plot_rag_scatter(file_title, analytics_file_path, rag_name, rag_data_list, category_map)
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


