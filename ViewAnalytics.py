import pandas as pd
import numpy as np
from datetime import datetime

import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Util as dmu
import DigiM_Notion as dmn


# 考察記事の特徴（TF-IDF）
def analytics_insight_tfidf(page_data, page_data_done, TopN=10):
    #形態素解析用の定義
    GRAMMER = ('名詞')#,'動詞','形容詞','副詞')
    STOP_WORDS = ["と", "の", "が", "で", "て", "に", "お", "は", "。", "、", "・", "<", ">", "【", "】", "(", ")", "（", "）", "Source", "Doc", "id", ":", "的", "等", "こと", "し", "する", "ます", "です", "します", "これ", "あれ", "それ", "どれ", "この", "あの", "その", "どの", "氏", "さん", "くん", "君", "化", "ため", "おり", "もの", "により", "あり", "これら", "あれら", "それら"]
    
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
    dmu.get_wordcloud(page_title, dict_tfidf_v)
    print(f"ワードクラウドを作成：ファイルを個別にNotionへ保存してください。{page_title}")
    
    return dict_tfidf_v, tfidf_topN, tfidf_topN_str


# 独自性：通常LLMとの差分
def analytics_insight_originality(page_data, vec_insight_final, vec_insight_draft, tfidf_topN=[]):
    # 通常LLMを実行してNotionに保存
    agent_file = "agent_01DigitalMATSUMOTO.json"
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

    # 独自のキーワード
    if tfidf_topN:
        original_keywords = [(keyword, value) for keyword, value in tfidf_topN if keyword not in insight_pure]
        dmn.update_notion_rich_text_content(page_data["id"], "独自性Final_キーワード", str(original_keywords))


# 知識参照度と知識活用度の分析
def analytics_insight_knowledge(page_data, topN=10):
    df = pd.DataFrame(eval(page_data["reference"]))
    
    # similarity_Qの統計量を算出
    similarity_Q_stats = {
        "max": df["similarity_Q"].max(),
        "min": df["similarity_Q"].min(),
        "mean": df["similarity_Q"].mean(),
        "median": df["similarity_Q"].median(),
        "variance": df["similarity_Q"].var()
    }
    
    # similarity_Qのランキングを取得
    similarity_Q_rank = df.nlargest(topN, "similarity_Q")[["ID", "similarity_Q", "similarity_A", "title", "text_short", "url"]].values.tolist()

    # similarity_Aの統計量を算出
    similarity_A_stats = {
        "max": df["similarity_A"].max(),
        "min": df["similarity_A"].min(),
        "mean": df["similarity_A"].mean(),
        "median": df["similarity_A"].median(),
        "variance": df["similarity_A"].var()
    }
    
    # similarity_Aのランキングを取得
    similarity_A_rank = df.nlargest(topN, "similarity_A")[["ID", "similarity_Q", "similarity_A", "title", "text_short", "url"]].values.tolist()

    # Notionへの書き込み
    dmn.update_notion_num(page_data["id"], "知識参照度Q_最大値", round(similarity_Q_stats["max"],3))
    dmn.update_notion_num(page_data["id"], "知識参照度Q_最小値", round(similarity_Q_stats["min"],3))
    dmn.update_notion_num(page_data["id"], "知識参照度Q_平均値", round(similarity_Q_stats["mean"],3))
    dmn.update_notion_num(page_data["id"], "知識参照度Q_中央値", round(similarity_Q_stats["median"],3))
    dmn.update_notion_num(page_data["id"], "知識参照度Q_分散", round(similarity_Q_stats["variance"],3))
    dmn.update_notion_rich_text_content(page_data["id"], "知識参照度Q_ランキング", str(similarity_Q_rank))

    dmn.update_notion_num(page_data["id"], "知識活用度A_最大値", round(similarity_A_stats["max"],3))
    dmn.update_notion_num(page_data["id"], "知識活用度A_最小値", round(similarity_A_stats["min"],3))
    dmn.update_notion_num(page_data["id"], "知識活用度A_平均値", round(similarity_A_stats["mean"],3))
    dmn.update_notion_num(page_data["id"], "知識活用度A_中央値", round(similarity_A_stats["median"],3))
    dmn.update_notion_num(page_data["id"], "知識活用度A_分散", round(similarity_A_stats["variance"],3))
    dmn.update_notion_rich_text_content(page_data["id"], "知識活用度A_ランキング", str(similarity_A_rank)) 


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
        "Model": {"実行モデル": "rich_text"},
        "reference": {"リファレンス": "rich_text"}
    }
    chk_dict_done = {'確定Chk': True}
    chk_dict_analyse = {'確定Chk': True, '分析Chk': False}
    date_dict = {}

    # 更新対象データの取得（コンテキストのPGを利用）
    page_data_analyse = dmc.get_chunk_notion(db_name, item_dict, chk_dict_analyse, date_dict)
    page_data_analyse = sorted(page_data_analyse, key=lambda x: x['note_date'], reverse=True)
    page_data_done = dmc.get_chunk_notion(db_name, item_dict, chk_dict_done, date_dict)
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
        
        # 考察の特徴：TF-IDFの分析
        dict_tfidf_v, tfidf_topN, tfidf_topN_str = analytics_insight_tfidf(page_data, page_data_done)
    
        # 独自性：通常LLMとの差分(距離)
        analytics_insight_originality(page_data, vec_insight_final, vec_insight_draft, tfidf_topN)

        # 知識参照度と活用度：質問及び回答とRAGデータの類似度
        analytics_insight_knowledge(page_data)
        
        # 分析の確定
        dmn.update_notion_chk(page_data["id"], "分析Chk", True)