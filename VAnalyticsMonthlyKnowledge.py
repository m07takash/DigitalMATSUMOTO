import os
import json
import ast
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
import matplotlib.pyplot as plt
from matplotlib import rcParams
from sklearn.decomposition import PCA
import chromadb

import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Util as dmu
import DigiM_Notion as dmn

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
mst_folder_path = os.getenv("MST_FOLDER")
rag_folder_json_path = os.getenv("RAG_FOLDER_JSON")
rag_folder_db_path = os.getenv("RAG_FOLDER_DB")
rcParams['font.family'] = 'Noto Sans CJK JP'
analytics_file_path = "user/common/analytics/monthly/"

# vector_data_value_textでPCAを算出してプロット
def plot_rag_scatter_thisMonth(end_month, rag_name, rag_data_list, category_map_json, months=1):
    end_date = datetime.strptime(end_month, "%Y-%m")
    end_of_month_str = (end_date + relativedelta(months=1) - timedelta(days=1)).date().strftime("%Y-%m-%d")
    start_of_month_str = (end_date - relativedelta(months=(months-1))).replace(day=1).date().strftime("%Y-%m-%d")

    # 検討対象を指定した月末までに設定
    df = pd.DataFrame(rag_data_list)
    df = df[pd.to_datetime(df['create_date']) <= pd.to_datetime(end_of_month_str)]
    
    df['vec_value_text_pca'] = df['vector_data_value_text'].apply(np.array)
    vectors = np.vstack(df['vec_value_text_pca'].to_numpy())
    pca = PCA(n_components=2)
    principal_components = pca.fit_transform(vectors)
    df['PC1'] = principal_components[:, 0]
    df['PC2'] = principal_components[:, 1]

    # Plot settings
    df['color'] = np.where(df['create_date'].between(start_of_month_str, end_of_month_str), 'blue', 'gray')
    plt.figure(figsize=(10, 8))
    plt.scatter(df['PC1'], df['PC2'], c=df['color'], alpha=0.7)
    plt.title(f'PCA Analysis: {rag_name}')
    plt.grid(True)
    plt.savefig(f"{analytics_file_path}{end_month}Monthly10_scatter{rag_name}.png", dpi=300, bbox_inches='tight')
    plt.show()

    # カテゴリーがあったら
    if 'category_color' in df.columns:
        plt.figure(figsize=(10, 8))
        plt.scatter(df['PC1'], df['PC2'], c=df['category_color'], alpha=0.7)
        plt.title(f'PCA Analysis(Category): {rag_name}')
        plt.grid(True)
        category_handles = [plt.Line2D([0], [0], marker='o', color='w', label=key, markersize=10, markerfacecolor=color)
                            for key, color in category_map_json["CategoryColor"].items()]
        category_handles.append(plt.Line2D([0], [0], marker='o', color='w', label='その他', markersize=10, markerfacecolor='gray'))
        plt.legend(handles=category_handles, loc='upper left', bbox_to_anchor=(1, 1), title="カテゴリー")
        plt.savefig(f"{analytics_file_path}{end_month}Monthly10_scatter{rag_name}_category.png", dpi=300, bbox_inches='tight')
        plt.show()


# 追加されたテキスト情報のワードクラウド（TF-IDF）
def wc_knowledge_tfidf(title, analyse_month, rag_data_month_list, TopN=10):
    GRAMMER = ('名詞')#,'動詞','形容詞','副詞')
    STOP_WORDS = ["と", "の", "が", "で", "て", "に", "お", "は", "。", "、", "・", "<", ">", "【", "】", "(", ")", "（", "）", "Source", "Doc", "id", ":", "的", "等", "こと", "し", "する", "ます", "です", "します", "これ", "あれ", "それ", "どれ", "この", "あの", "その", "どの", "氏", "さん", "くん", "君", "化", "ため", "おり", "もの", "により", "あり", "これら", "あれら", "それら", "・・", "*", "#", ":", ";", "「", "」", "感", "性", "ば", "かも", "ごと"]

    # TF-IDF用のデータ
    value_text_list = [rag_data["value_text"] for rag_data in rag_data_month_list]    
    value_text_month = next((rag_data["value_text"] for rag_data in rag_data_month_list if rag_data["month"]==analyse_month), None)

    if value_text_month:
        # TF-IDFベクトライザーを生成
        vectorizer_tfidf = dmu.fit_tfidf(value_text_list, mode="Default", stop_words=STOP_WORDS, grammer=GRAMMER)
        dict_tfidf, tfidf_topN, tfidf_topN_str = dmu.get_tfidf_list(value_text_month, vectorizer_tfidf, TopN)
        dict_tfidf_v = {key: value for key, value in dict_tfidf.items() if value != 0}
    
        # TF-IDFのTop10をテキスト出力
        with open(f"{analytics_file_path}TFIDF_topN_{analyse_month}{title}.txt", "w", encoding="utf-8") as file:
            file.write(tfidf_topN_str)
        
        # ワードクラウドを生成して保存
        dmu.get_wordcloud(f"TFIDF_{analyse_month}{title}", dict_tfidf_v, analytics_file_path)
    

# ナレッジデータの分析
def analytics_knowledge_monthly(end_month, months=1):   
    # エージェントの設定
    agent_file = "agent_01DigitalMATSUMOTO_GPT.json"
    agent = dma.DigiM_Agent(agent_file)

    # カテゴリーマップの取得
    category_map_file = "category_map.json"
    category_map_json = dmu.read_json_file(category_map_file, mst_folder_path)

    # 知識情報(RAG)の取得
    for knowledge in agent.knowledge:
        rag_name = knowledge["RAG_NAME"]
        rag_data_list = []
        for rag_data in knowledge["DATA"]:
            if rag_data["DATA_TYPE"] == "JSON":
                rag_data_file = rag_data["DATA_NAME"] +'_vec.json'
                rag_data_json = dmu.read_json_file(rag_data_file, rag_folder_json_path)
                for k, v in rag_data_json.items():
                    v["month"] = v["create_date"][:7]
                    if 'category' in v:
                        v["category_sum"] = category_map_json["Category"].get(v["category"], "その他")
                        if v["category_sum"] in category_map_json["CategoryColor"]:
                            v["category_color"] = category_map_json["CategoryColor"][v["category_sum"]]
                        else:
                            v["category_color"] = "gray"
                    rag_data_list.append(v)
            elif rag_data["DATA_TYPE"] == "DB":
                db_client = chromadb.PersistentClient(path=rag_folder_db_path)
                collection = db_client.get_collection(rag_data["DATA_NAME"])
                rag_data_db = collection.get(include=["metadatas", "embeddings"])
                for i in range(len(rag_data_db["ids"])):
                    v = {}
                    v["id"] = rag_data_db["ids"][i]
                    v |= rag_data_db["metadatas"][i]
                    v["vector_data_value_text"] = ast.literal_eval(v["vector_data_value_text"])
                    v["vector_data_key_text"] = rag_data_db["embeddings"][i].tolist()
                    v["month"] = v["create_date"][:7]
                    if 'category' in v:
                        v["category_sum"] = category_map_json["Category"].get(v["category"], "その他")
                        if v["category_sum"] in category_map_json["CategoryColor"]:
                            v["category_color"] = category_map_json["CategoryColor"][v["category_sum"]]
                        else:
                            v["category_color"] = "gray"                        
                    rag_data_list.append(v)
        
        # チャンクデータ(PCA)の散布図を作成
        plot_rag_scatter_thisMonth(end_month, rag_name, rag_data_list, category_map_json, months)

        # TF-IDF分析用に｛月：チャンクテキスト｝の形式でデータを整形
        rag_data_month = {}
        for rag_data in rag_data_list:
            month = rag_data["month"]
            value_text = rag_data["value_text"]
            if month in rag_data_month:
                rag_data_month[month] += "\n" + value_text
            else:
                rag_data_month[month] = value_text
        rag_data_month_list = [{"month": month, "value_text": value_text} for month, value_text in rag_data_month.items()]

        # 当月チャンクデータのTF-IDFワードクラウドの出力
        wc_knowledge_tfidf(rag_name, end_month, rag_data_month_list, 10)