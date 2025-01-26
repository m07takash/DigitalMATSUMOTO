import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib import rcParams

import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Util as dmu
import DigiM_Notion as dmn

analytics_file_path = "user/common/analytics/insight/"

# 考察記事の特徴（TF-IDF）
def analytics_insight_tfidf(page_data, page_data_done, TopN=10):
    # 形態素解析用の定義
    GRAMMER = ('名詞')#,'動詞','形容詞','副詞')
    STOP_WORDS = ["と", "の", "が", "で", "て", "に", "お", "は", "。", "、", "・", "<", ">", "【", "】", "(", ")", "（", "）", "Source", "Doc", "id", ":", "的", "等", "こと", "し", "する", "ます", "です", "します", "これ", "あれ", "それ", "どれ", "この", "あの", "その", "どの", "氏", "さん", "くん", "君", "化", "ため", "おり", "もの", "により", "あり", "これら", "あれら", "それら", "・・", "*", "#", ":", ";", "「", "」", "感", "性", "ば", "かも", "ごと"]
    
    # ページタイトルを取得
    page_title = page_data["title"]

    # TF-IDF設定対象の取得
    page_date = datetime.strptime(page_data['note_date'], '%Y-%m-%d')
    insights = [page["Insight_Final"] for page in page_data_done if datetime.strptime(page['note_date'], '%Y-%m-%d') <= page_date]
    
    # TF-IDFベクトライザーを生成
    vectorizer_tfidf = dmu.fit_tfidf(insights, mode="Default", stop_words=STOP_WORDS, grammer=GRAMMER)
    dict_tfidf, tfidf_topN, tfidf_topN_str = dmu.get_tfidf_list(page_data["Insight_Final"], vectorizer_tfidf, TopN)
    dict_tfidf_v = {key: value for key, value in dict_tfidf.items() if value != 0}

    # TF-IDFをNotionに保存
    result = dmn.update_notion_rich_text_content(page_data["id"], "TF-IDFトップ10", tfidf_topN_str)
    
    # ワードクラウドを生成して保存
    dmu.get_wordcloud(page_title, dict_tfidf_v, analytics_file_path)
    print(f"ワードクラウドを作成：ファイルを個別にNotionへ保存してください。{page_title}")
    
    return dict_tfidf_v, tfidf_topN, tfidf_topN_str


# 独自性：通常LLMとの差分
def analytics_insight_originality(page_data, vec_insight_final, vec_insight_draft, tfidf_topN=[]):
    # 通常LLMを実行してNotionに保存
#    agent_file = "agent_01DigitalMATSUMOTO_GPT.json"
    agent_file = page_data["agent"]
    insight_pure, prompt_tokens, response_tokens = dmt.generate_pureLLM(agent_file, page_data["Input"])
    vec_insight_pure = dmu.embed_text(insight_pure)
    dmn.update_notion_rich_text_content(page_data["id"], "考察_比較LLM", insight_pure)

    # 独自性(距離)を算出
    originality_final = dmu.calculate_cosine_distance(vec_insight_final, vec_insight_pure)
    originality_draft = dmu.calculate_cosine_distance(vec_insight_draft, vec_insight_pure)
    originality_improved = originality_final - originality_draft
    result = dmn.update_notion_num(page_data["id"], "独自性(距離)Final", originality_final)
    result = dmn.update_notion_num(page_data["id"], "独自性(距離)Draft", originality_draft)
    result = dmn.update_notion_num(page_data["id"], "独自性(距離)Improved", originality_improved)

    # LLMでの比較分析
    compare_final_pure, prompt_tokens, response_tokens = dmt.compare_texts("デジタルMATSUMOTOの考察(最終版)", page_data["Insight_Final"], "通常LLMの考察", insight_pure)
    compare_draft_pure, prompt_tokens, response_tokens = dmt.compare_texts("デジタルMATSUMOTOの考察(ドラフト版)", page_data["Insight_Draft"], "通常LLMの考察", insight_pure)
    compare_final_draft, prompt_tokens, response_tokens = dmt.compare_texts("デジタルMATSUMOTOの考察(最終版)", page_data["Insight_Final"], "デジタルMATSUMOTOの考察(ドラフト版)", page_data["Insight_Draft"])
    dmn.update_notion_rich_text_content(page_data["id"], "独自性Final_LLM評価", compare_final_pure.replace("*",""))
    dmn.update_notion_rich_text_content(page_data["id"], "独自性Draft_LLM評価", compare_draft_pure.replace("*",""))
    dmn.update_notion_rich_text_content(page_data["id"], "独自性Improved_LLM評価", compare_final_draft.replace("*",""))

    # TF-IDFから独自キーワードを算出
    if tfidf_topN:
        sum_tfidf_topN = 0
        sum_tfidf_original = 0
        original_keywords = []
        for keyword, value in tfidf_topN:
            sum_tfidf_topN += value
            if keyword not in insight_pure:
                sum_tfidf_original += value
                original_keywords.append((keyword, value))
                
        rate_tfidf_original = 0
        if sum_tfidf_topN != 0 and sum_tfidf_original != 0:
            rate_tfidf_original = sum_tfidf_original / sum_tfidf_topN
            
        dmn.update_notion_rich_text_content(page_data["id"], "TF-IDF独自性Final", str(original_keywords))
        result = dmn.update_notion_num(page_data["id"], "TF-IDF合計_トップ10", sum_tfidf_topN)
        result = dmn.update_notion_num(page_data["id"], "TF-IDF合計_独自", sum_tfidf_original)
        result = dmn.update_notion_num(page_data["id"], "TF-IDF合計_割合", rate_tfidf_original)


# 知識参照度と知識活用度の分析
def analytics_insight_knowledge(page_data, topN=10):
    df = pd.DataFrame(eval(page_data["reference"]))
    df['knowledge_utility'] = df['similarity_Q'] - df['similarity_A']

    page_title = page_data["title"][:30]
    
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
    
    # similarityのランキングを取得
    similarity_rank = (df.sort_values(['rag', 'similarity_Q'], ascending=[True, False]).groupby('rag')[['ID', 'title', 'similarity_Q', 'similarity_A','knowledge_utility']].apply(lambda x: x.to_dict(orient='records')).to_dict())
    
    # RAGごとの知識活用性（Q最小値-A最小値）を算出
    #min_difference = similarity_Q_stats['min'] - similarity_A_stats['min']
    #min_difference_dict = dict(zip(similarity_Q_stats['rag'], min_difference))
    knowledge_utility_stats_dict = dict(zip(similarity_Q_stats['rag'], knowledge_utility_stats['max']))
    
    # Notionへの書き込み
    dmn.update_notion_rich_text_content(page_data["id"], "知識参照度Q", str(similarity_Q_stats.to_dict(orient='index'))) 
    dmn.update_notion_rich_text_content(page_data["id"], "知識活用度A", str(similarity_A_stats.to_dict(orient='index'))) 
    #dmn.update_notion_rich_text_content(page_data["id"], "知識活用性", str(min_difference_dict)) 
    dmn.update_notion_rich_text_content(page_data["id"], "知識活用性", str(knowledge_utility_stats_dict)) 

    # 知識活用性ランキングのテキスト出力
    with open(f"{analytics_file_path}知識活用性ランキング_{page_title}.txt", "w", encoding="utf-8") as file:
        file.write(str(similarity_rank))

    # Sort data by similarity_Q in descending order within each rag
    sorted_plot_data = df.sort_values(by=['rag', 'similarity_Q'], ascending=[True, False])

    # フォントを設定
    rcParams['font.family'] = 'Noto Sans CJK JP'  # 使用する日本語フォント名

    # Plot horizontal bar chart for each 'rag', ensuring bars do not overlap
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
        filename = f"{analytics_file_path}{page_title}_{rag}_similarity_plot.png"
        #plt.tight_layout()
        plt.savefig(filename)
        plt.close(fig)


# 考察の分析
def analytics_insights():
    db_name = "DigiMATSU_Opinion"
    item_dict = {
        "title": {"名前": "title"}, 
        "note_date": {"note公開日": "date"},
        "category": {"カテゴリ": "select"},
        "eval": {"評価": "select"},
        "Input": {"インプット": "rich_text"},
        "Insight_Draft": {"考察_DTwin": "rich_text"},
        "Insight_Final": {"考察_確定版": "rich_text"},
        "agent": {"エージェントファイル": "rich_text"},
        "model": {"実行モデル": "rich_text"},
        "Point_RealM": {"リアル松本の論点数": "number"},
        "Point_DigiM": {"実現できた論点数": "number"},
        "reference": {"リファレンス": "rich_text"}
    }
    chk_dict_done = {'分析対象Chk': True}
    chk_dict_analyse = {'分析対象Chk': True, '分析Chk': False}
    date_dict = {}

    # 更新対象データの取得（コンテキストのPGを利用）
    page_data_analyse = dmc.get_chunk_notion("Analyse", db_name, item_dict, chk_dict_analyse, date_dict)
    page_data_analyse = sorted(page_data_analyse, key=lambda x: x['note_date'], reverse=True)
    page_data_done = dmc.get_chunk_notion("Done", db_name, item_dict, chk_dict_done, date_dict)
    page_data_done = sorted(page_data_done, key=lambda x: x['note_date'], reverse=True)

    # ページごとに取得
    for page_data in page_data_analyse:
        # テキストのベクトル化
        vec_input = dmu.embed_text(page_data["Input"])
        vec_insight_final = dmu.embed_text(page_data["Insight_Final"])
        vec_insight_draft = dmu.embed_text(page_data["Insight_Draft"])
        
        # 実現性：リアル松本との差分(類似度)
        realization = 1 - dmu.calculate_cosine_distance(vec_insight_final, vec_insight_draft)
        dmn.update_notion_num(page_data["id"], "実現性(類似度)", realization)

        # 論点再現度
        realization_point = 0
        if page_data["Point_RealM"]:
            if page_data["Point_RealM"] > 0 and page_data["Point_DigiM"] > 0:
                realization_point = round(page_data["Point_DigiM"]/page_data["Point_RealM"], 10)
        dmn.update_notion_num(page_data["id"], "論点再現度", realization_point)
        
        # 考察の特徴：TF-IDFの分析
        dict_tfidf_v, tfidf_topN, tfidf_topN_str = analytics_insight_tfidf(page_data, page_data_done)
    
        # 独自性：通常LLMとの差分(距離)
        analytics_insight_originality(page_data, vec_insight_final, vec_insight_draft, tfidf_topN)

        # 知識参照度と活用度：質問及び回答とRAGデータの類似度
        analytics_insight_knowledge(page_data)
        
        # 分析の確定
        dmn.update_notion_chk(page_data["id"], "分析Chk", True)
        print(page_data["title"]+"の分析が完了しました。")
        