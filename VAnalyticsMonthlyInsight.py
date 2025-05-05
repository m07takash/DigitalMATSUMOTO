import os
import ast
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from collections import defaultdict
import matplotlib.pyplot as plt
from matplotlib import rcParams

import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Util as dmu
import DigiM_Notion as dmn

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
mst_folder_path = os.getenv("MST_FOLDER")
rcParams['font.family'] = 'Noto Sans CJK JP'
analytics_file_path = "user/common/analytics/monthly/"

# note表示用にデータフレームをkatex用に変換
def dataframe_to_katex(df):
    katex_str = "$$\n\\begin{array}{" + "|" + "|".join(["l" for _ in df.columns]) + "|}\\hline\n"
    header_row = " & ".join([f"\\textbf{{{col}}}" for col in df.columns])
    katex_str += header_row + " \\\\ \\hline\n"
    for _, row in df.iterrows():
        data_row = " & ".join([str(val) for val in row])
        katex_str += data_row + " \\\\ \\hline\n"
    katex_str += "\\end{array}\n$$"
    return katex_str


# 分析対象データの取得（"yyyy-mm"で指定）
def get_analytics_data(end_month, months=12):
    end_date = datetime.strptime(end_month, "%Y-%m")
    end_of_month_str = (end_date + relativedelta(months=1) - timedelta(days=1)).date().strftime("%Y-%m-%d")
    start_of_month_str = (end_date - relativedelta(months=(months-1))).replace(day=1).date().strftime("%Y-%m-%d")

    db_name = "DigiMATSU_Opinion"
    item_dict = {
        "title": {"名前": "title"}, 
        "note_date": {"note公開日": "date"},
        "category_dtl": {"カテゴリ": "select"},
        "model": {"実行モデル": "rich_text"},
        "o1_final": {"独自性(距離)Final": "number"},
        "o1_draft": {"独自性(距離)Draft": "number"},
        "o1_improved": {"独自性(距離)Improved": "number"},
        "o2_tfidf_rate": {"TF-IDF合計_割合": "number"},
        "o2_tfidf_original": {"TF-IDF合計_独自": "number"},
        "o2_tfidf_top10": {"TF-IDF合計_トップ10": "number"},
        "r1_eval_raw": {"評価": "select"},
        "r2_similarity": {"実現性(類似度)": "number"},
        "r3_point": {"論点再現度": "number"},
        "r3_point_DigiM": {"実現できた論点数": "number"},
        "r3_point_RealM": {"リアル松本の論点数": "number"},
        "k1_util": {"知識活用性": "rich_text"},
        "k1_Q": {"知識参照度Q": "rich_text"},
        "k1_A": {"知識活用度A": "rich_text"},
        "k1_Rank": {"知識活用性ランキング": "rich_text"},
        "i1_improve": {"自己修正(距離)": "number"},
        "i2_improve": {"自己改善効果(類似度の変化)": "number"},
        "url": {"URL": "url"}
    }
    chk_dict_analyse = {'確定Chk': True, '分析Chk': True} #分析対象ではなく「確定」したデータのみを対象（考察として確定し、RAGにも反映しているデータ）
    date_dict = {
        "note公開日":[start_of_month_str, end_of_month_str]
    }
    
    # 更新対象データの取得（コンテキストのPGを利用）
    page_data_analyse = dmc.get_chunk_notion("Analyse", db_name, item_dict, chk_dict_analyse, date_dict)
    page_data_analyse = sorted(page_data_analyse, key=lambda x: x['note_date'], reverse=True)
    
    # カテゴリーマップの取得
    category_map_file = "category_map.json"
    category_map_json = dmu.read_json_file(category_map_file, mst_folder_path)

    # 評価スコアマップの取得
    eval_score_map = {"P": 1, "A": 0.7, "B": 0.4, "C": 0.1, "D": -0.5, "E": -1}
    eval_color_map = {"P": "purple", "A": "blue", "B": "cyan", "C": "yellow", "D": "orange", "E": "red"}

    # データ項目の追加
    for page_data in page_data_analyse:
        page_data['month'] = datetime.strptime(page_data['note_date'], '%Y-%m-%d').strftime('%Y-%m')       
        if page_data["category_dtl"] in category_map_json["Category"]:
            page_data["category"] = category_map_json["Category"][page_data["category_dtl"]]
            if page_data["category"] in category_map_json["CategoryColor"]:
                page_data["category_color"] = category_map_json["CategoryColor"][page_data["category"]]
        page_data['r1_eval'] = page_data['r1_eval_raw'][:1]
        page_data["r1_score"] = eval_score_map.get(page_data['r1_eval'], 0)
        for key in ["P","A","B","C","D","E"]:
            if key == page_data["r1_eval"]:
                page_data[f"r1_eval_{key}"] = 1
            else:
                page_data[f"k1_eval_{key}"] = 0
        page_data["r1_eval_color"] = eval_color_map.get(page_data['r1_eval'], "grey")
        for key in ["Opinion","Policy","Communication"]:
            page_data[f"k1_util_{key}"] = 0
            if page_data["k1_util"]:
                if key in eval(page_data["k1_util"]).keys():
                    page_data[f"k1_util_{key}"] = eval(page_data["k1_util"])[key]
    
    return page_data_analyse


# 月ごとのカテゴリごとの件数を集計
def plot_count_monthly(df, analyse_month):    
    category_monthly_counts = df.groupby(['month', 'category']).size().unstack(fill_value=0).iloc[:, ::-1]
    
    # 積み上げ棒グラフを作成
    colors = {row['category']: row['category_color'] for _, row in df.iterrows()}
    ax = category_monthly_counts.plot(kind='bar', stacked=True, color=[colors.get(cat, 'gray') for cat in category_monthly_counts.columns], figsize=(10, 6))
    for container in ax.containers:
        labels = [f"{int(v)}" if v > 0 else "" for v in container.datavalues]
        ax.bar_label(container, label_type='center', fmt='%d')
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], labels[::-1], loc='upper left', bbox_to_anchor=(1.0, 1.0), title='Category')
    ax.set_xlabel('Month')
    ax.set_ylabel('Count')
    ax.set_title('Monthly Count by Category')
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(f"{analytics_file_path}{analyse_month}Monthly01Cnt.png", dpi=300, bbox_inches='tight')
    #plt.show()

# 月ごとの評価ランクごとの件数を集計
def plot_rank_monthly(df, analyse_month):    
    # カテゴリの順序を指定
    eval_order = ["P", "A", "B", "C", "D", "E"][::-1]
    df['r1_eval'] = pd.Categorical(df['r1_eval'], categories=eval_order, ordered=True)

    category_monthly_counts = df.groupby(['month', 'r1_eval']).size().unstack(fill_value=0)
    
    # 積み上げ棒グラフを作成
    colors = {row['r1_eval']: row['r1_eval_color'] for _, row in df.iterrows()}
    ax = category_monthly_counts.plot(kind='bar', stacked=True, color=[colors.get(cat, 'gray') for cat in category_monthly_counts.columns], figsize=(10, 6))
    for container in ax.containers:
        labels = [f"{int(v)}" if v > 0 else "" for v in container.datavalues]
        ax.bar_label(container, label_type='center', fmt='%d')
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], labels[::-1], loc='upper left', bbox_to_anchor=(1.0, 1.0), title='Rank')
    ax.set_xlabel('Month')
    ax.set_ylabel('Count')
    ax.set_title('Monthly Count by Rank')
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(f"{analytics_file_path}{analyse_month}Monthly04_r1_rank.png", dpi=300, bbox_inches='tight')
    #plt.show()


# 対象月の統計情報
def statics_this_month(df_thisMonth, analyse_month):    
    stats_thisMonth_overview = {
        'Metric': ['Max', 'Min', 'Mean', 'Median', 'Variance', 'Sum'],
        'A-1.独自性(Cos距離)': [df_thisMonth['o1_final'].max(), df_thisMonth['o1_final'].min(), df_thisMonth['o1_final'].mean(), df_thisMonth['o1_final'].median(), df_thisMonth['o1_final'].var(), df_thisMonth['o1_final'].sum()],
        'A-1.独自性_ドラフト時点': [df_thisMonth['o1_draft'].max(), df_thisMonth['o1_draft'].min(), df_thisMonth['o1_draft'].mean(), df_thisMonth['o1_draft'].median(), df_thisMonth['o1_draft'].var(), df_thisMonth['o1_draft'].sum()],
        'A-1.独自性_改善度': [df_thisMonth['o1_improved'].max(), df_thisMonth['o1_improved'].min(), df_thisMonth['o1_improved'].mean(), df_thisMonth['o1_improved'].median(), df_thisMonth['o1_improved'].var(), df_thisMonth['o1_improved'].sum()],
        'A-2.独自キーワード(割合)': [df_thisMonth['o2_tfidf_rate'].max(), df_thisMonth['o2_tfidf_rate'].min(), df_thisMonth['o2_tfidf_rate'].mean(), df_thisMonth['o2_tfidf_rate'].median(), df_thisMonth['o2_tfidf_rate'].var(), df_thisMonth['o2_tfidf_rate'].sum()],
        'A-2.独自キーワード(TF-IDF)': [df_thisMonth['o2_tfidf_original'].max(), df_thisMonth['o2_tfidf_original'].min(), df_thisMonth['o2_tfidf_original'].mean(), df_thisMonth['o2_tfidf_original'].median(), df_thisMonth['o2_tfidf_original'].var(), df_thisMonth['o2_tfidf_original'].sum()],
        'A-2.Top10キーワード(TF-IDF)': [df_thisMonth['o2_tfidf_top10'].max(), df_thisMonth['o2_tfidf_top10'].min(), df_thisMonth['o2_tfidf_top10'].mean(), df_thisMonth['o2_tfidf_top10'].median(), df_thisMonth['o2_tfidf_top10'].var(), df_thisMonth['o2_tfidf_top10'].sum()],
        'B-1.評価ランク(対応値)': [df_thisMonth['r1_score'].max(), df_thisMonth['r1_score'].min(), df_thisMonth['r1_score'].mean(), df_thisMonth['r1_score'].median(), df_thisMonth['r1_score'].var(), df_thisMonth['r1_score'].sum()],
        'B-2.実現度合(Cos類似度)': [df_thisMonth['r2_similarity'].max(), df_thisMonth['r2_similarity'].min(), df_thisMonth['r2_similarity'].mean(), df_thisMonth['r2_similarity'].median(), df_thisMonth['r2_similarity'].var(), df_thisMonth['r2_similarity'].sum()],
        'B-3.論点再現度(割合)': [df_thisMonth['r3_point'].max(), df_thisMonth['r3_point'].min(), df_thisMonth['r3_point'].mean(), df_thisMonth['r3_point'].median(), df_thisMonth['r3_point'].var(), df_thisMonth['r3_point'].sum()],
        'C-1.知識活用性_Opinion': [df_thisMonth['k1_util_Opinion'].max(), df_thisMonth['k1_util_Opinion'].min(), df_thisMonth['k1_util_Opinion'].mean(), df_thisMonth['k1_util_Opinion'].median(), df_thisMonth['k1_util_Opinion'].var(), df_thisMonth['k1_util_Opinion'].sum()], 
        'C-2.知識活用性_Policy': [df_thisMonth['k1_util_Policy'].max(), df_thisMonth['k1_util_Policy'].min(), df_thisMonth['k1_util_Policy'].mean(), df_thisMonth['k1_util_Policy'].median(), df_thisMonth['k1_util_Policy'].var(), df_thisMonth['k1_util_Policy'].sum()], 
        'C-3.知識活用性_Communication': [df_thisMonth['k1_util_Communication'].max(), df_thisMonth['k1_util_Communication'].min(), df_thisMonth['k1_util_Communication'].mean(), df_thisMonth['k1_util_Communication'].median(), df_thisMonth['k1_util_Communication'].var(), df_thisMonth['k1_util_Communication'].sum()],
        'D-1.自己修正(距離)': [df_thisMonth['i1_improve'].max(), df_thisMonth['i1_improve'].min(), df_thisMonth['i1_improve'].mean(), df_thisMonth['i1_improve'].median(), df_thisMonth['i1_improve'].var(), df_thisMonth['i1_improve'].sum()],
        'D-2.自己改善効果(類似度の変化)': [df_thisMonth['i2_improve'].max(), df_thisMonth['i2_improve'].min(), df_thisMonth['i2_improve'].mean(), df_thisMonth['i2_improve'].median(), df_thisMonth['i2_improve'].var(), df_thisMonth['i2_improve'].sum()]
    }

    df_thisMonth_overview = pd.DataFrame(stats_thisMonth_overview).round(3).transpose()
    df_thisMonth_overview.to_csv(f"{analytics_file_path}{analyse_month}Monthly02Summary.csv", index=True, encoding='utf-8-sig')

    return df_thisMonth_overview


# データの月別変遷
def plot_time_series_item(df, item, analyse_month, cols=['max_value', 'min_value', 'mean_value']):
    aggregated_data = df.groupby('month')[item].agg(max_value='max', min_value='min', mean_value='mean', median_value='median', variance_value='var').reset_index()
    
    # 集計対象項目から表示名を設定
    display_item_map = {
        "o1_final": "A-1.独自性(Cos距離)", 
        "o1_draft": "A-1.独自性_ドラフト時点", 
        "o1_improved": "A-1.独自性_改善度", 
        "o2_tfidf_rate": "A-2.独自キーワード(割合)", 
        "r1_score": "B-1.評価ランク(対応値)",
        "r2_similarity": "B-2.実現度合(Cos類似度)", 
        "r3_point": "B-3.論点再現度(割合)", 
        "k1_util_Opinion": "C-1.知識活用性_Opinion", 
        "k1_util_Policy": "C-2.知識活用性_Policy", 
        "k1_util_Communication": "C-3.知識活用性_Communication",
        "i1_improve": "D-1.自己修正(距離)",
        "i2_improve": "D-2.自己改善効果(類似度の変化)"
    }
    display_item = display_item_map.get(item, item)
        
    fig, ax = plt.subplots(figsize=(12, 6))
    for col in cols:
        plt.plot(aggregated_data['month'].astype(str), aggregated_data[col], marker='o', label=col)
        # データポイントに数値を表示
        for i, txt in enumerate(aggregated_data[col]):
            plt.text(i, txt, f'{txt:.3f}', ha='center', va='bottom', fontsize=8)

    # グラフの装飾
    ax.set_title(display_item, fontsize=14)
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Value", fontsize=12)
    ax.legend(title="Statistics", loc='upper left', bbox_to_anchor=(1.0, 1.0))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{analytics_file_path}{analyse_month}Monthly05_{item}_timeseries.png", dpi=300, bbox_inches='tight')
    #plt.show()

# 当月の知識活用ランキングの出力
def df_knowledge_use_ranking(df, analyse_month, rank_num=10):
    # 'k1_Rank'列をリスト化し、文字列データを辞書に変換
    data = df["k1_Rank"].tolist()
    parsed_data = []
    for category in data:
        parsed_data.append(ast.literal_eval(category))
        
    aggregated_data = defaultdict(lambda: {'title': '', 'knowledge_utility': 0})
    for category_dict in parsed_data:
        for category_key, items in category_dict.items():
            for item in items:
                #key = item['ID']
                key = (category_key, item['ID'])                
                aggregated_data[key]['title'] = item['title']
                aggregated_data[key]['knowledge_utility'] += item['knowledge_utility']

    # knowledge_utility の降順でソート
#    sorted_data = sorted(
#        [{'ID': k, 'title': v['title'], 'knowledge_utility': v['knowledge_utility']} for k, v in aggregated_data.items()],
#        key=lambda x: x['knowledge_utility'],
#        reverse=True
#    )
    
    # 各カテゴリーごとにTopNを取得
#    results = {}
#    first_category = parsed_data[0] if parsed_data else {}
#    for category_key in first_category.keys():
#        category_items = [item for cat in parsed_data for item in cat[category_key]]
#        category_ids = {item['ID'] for item in category_items}
#        filtered_data = [item for item in sorted_data if item['ID'] in category_ids]
        
        # Top N件のデータを保存
#        results[category_key] = filtered_data[:rank_num]
#        with open(f"{analytics_file_path}{analyse_month}Monthly06_RAGTopN_{category_key}.txt", "w", encoding="utf-8") as file:
#            file.write(str(results[category_key]))
    
    results = defaultdict(list)
    for (cat_key, id_key), vals in aggregated_data.items():
        results[cat_key].append({
            'ID': id_key,
            'title': vals['title'],
            'knowledge_utility': vals['knowledge_utility']
        })
    
    # カテゴリごとに knowledge_utility で降順ソートして上位N件をテキスト出力
    for cat_key, items_list in results.items():
        sorted_list = sorted(items_list, key=lambda x: x['knowledge_utility'], reverse=True)
        topN_list = sorted_list[:rank_num]
        
        output_path = f"{analytics_file_path}{analyse_month}Monthly06_RAGTopN_{cat_key}.txt"
        with open(output_path, "w", encoding="utf-8") as file:
            file.write(str(topN_list))


    
# 月次考察の分析
def analytics_insights_monthly(analyse_month, months = 12):
    page_data_analyse = get_analytics_data(analyse_month, months)
    df = pd.DataFrame(page_data_analyse)
    df_thisMonth = df[(df['month'] == analyse_month)]
    
    # マーク用の列を初期化
    df_thisMonth['BEST_Mark'] = ''
    df_thisMonth['Top5_Mark'] = ''
    target_columns = ["o1_final", "o1_improved", "o2_tfidf_rate", "r1_score", "r2_similarity", "r3_point", "k1_util_Opinion", "k1_util_Policy", "k1_util_Communication", "i1_improve", "i2_improve"]
    for col in target_columns:
        best_indices = df_thisMonth[col].nlargest(1).index
        df_thisMonth.loc[best_indices, 'BEST_Mark'] += f'{col}_BEST; '
        top5_indices = df_thisMonth[col].nlargest(5).index
        df_thisMonth.loc[top5_indices, 'Top5_Mark'] += f'{col}_TOP5; '

    # 月ごとのカテゴリごとの件数を集計
    plot_count_monthly(df, analyse_month)
    
    # 月ごとのランクごとの件数を集計
    plot_rank_monthly(df, analyse_month)
    
    # データの月別変遷
    for item in target_columns:
        plot_time_series_item(df, item, analyse_month)
    
    # 当月の統計情報を計算
    df_thisMonth_overview = statics_this_month(df_thisMonth, analyse_month)
    #display(df_thisMonth_overview)
    
    # 当月のデータ出力
    columns_to_select = ["note_date", "title", "category", "o1_final", "o1_draft", "o1_improved", "o2_tfidf_rate", "r1_eval", "r2_similarity", "r3_point", "k1_util_Opinion", "k1_util_Policy", "k1_util_Communication", "i1_improve", "i2_improve", "BEST_Mark", "Top5_Mark"]
    df_thisMonth[columns_to_select].to_csv(f"{analytics_file_path}{analyse_month}Monthly03Insight.csv", index=True, header=["日付", "タイトル", "カテゴリー", "A-1.独自性(Cos距離)", "A-1.独自性_ドラフト時点", "A-1.独自性_改善度", "A-2.独自キーワード(割合)", "B-1.評価ランク", "B-2.実現度合(Cos類似度)", "B-3.論点再現度(割合)", "C-1.知識活用性_Opinion", "C-2.知識活用性_Policy", "C-3.知識活用性_Communication", "D-1.自己修正(距離)", "D-2.自己改善効果(類似度の変化)", "BEST_Mark", "Top5_Mark"], encoding='utf-8-sig')
    #display(df_thisMonth[columns_to_select])

    # 当月の知識活用ランキングの出力
    df_knowledge_use_ranking(df_thisMonth, analyse_month)
