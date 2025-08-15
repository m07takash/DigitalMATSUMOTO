import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams

# 知識参照度と知識活用度の分析
def analytics_knowledge(title, reference, analytics_file_path):
    df = pd.DataFrame(reference)

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
        ax.barh([y - bar_height / 2 for y in y_positions], group['similarity_Q'], height=bar_height, color='blue', label='similarity_Q')
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
