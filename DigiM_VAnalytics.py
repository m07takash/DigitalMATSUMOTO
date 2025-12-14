import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams

import DigiM_Agent as dma
import DigiM_Execute as dme

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

# 知識参照度と知識活用度の分析
def analytics_knowledge(title, reference, analytics_file_path, ak_mode="Default"):
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
    file_title = title[:30]
    
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

    # Plot horizontal bar chart for each 'rag', ensuring bars do not overlap
    similarity_plot_files = []
    
    for rag, group in sorted_plot_data.groupby('rag'):
        fig, ax = plt.subplots(figsize=(24, 8))
        bar_height = 0.4  # Adjust bar height to separate the bars
        
        # Calculate positions for the bars
        y_positions = range(len(group))
        
#        q_colors = ["blue" if mode == "NORMAL" else "deepskyblue" for mode in group['QUERY_MODE']]
        color_map = {
            "1": ("blue", "lightskyblue"),
            "2": ("navy", "cornflowerblue"),
            "default": ("deepskyblue", "powderblue")
        }

        q_colors = [
            (
                color_map.get(seq, color_map["default"])[0]
                if mode == "NORMAL"
                else color_map.get(seq, color_map["default"])[1]
            )
            for seq, mode in zip(group["QUERY_SEQ"], group["QUERY_MODE"])
        ]

        ax.barh([y - bar_height / 2 for y in y_positions], group['similarity_Q'], height=bar_height, color=q_colors, label='similarity_Q')
        ax.barh([y + bar_height / 2 for y in y_positions], group['similarity_A'], height=bar_height, color='orange', label='similarity_A')
        
        # Set labels and title
        ax.set_xlabel('Similarity Distance', fontsize=12)
        ax.set_ylabel('Title', fontsize=12)
        ax.set_title(f'{rag} - Similarity_Q vs Similarity_A (Sorted by Similarity_Q Desc)', fontsize=14)
        ax.set_yticks(y_positions)
        ax.set_yticklabels(group['title'], fontsize=8)
        ax.legend()
        
        # Save plot as an image file
        similarity_plot_file = f"{file_title}_KUtilPlot_{rag}.png"
        similarity_plot_files.append(similarity_plot_file)
        filename = analytics_file_path+similarity_plot_file
        plt.savefig(filename)
        plt.close(fig)
    
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
            "similarity_plot_file": similarity_plot_files
            }
    }
    
    return result


