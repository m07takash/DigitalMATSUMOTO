import os
import re
import json
from datetime import datetime
from dotenv import load_dotenv
import DigiM_Util as dmu

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
user_folder_path = system_setting_dict["USER_FOLDER"]
session_folder_prefix = system_setting_dict["SESSION_FOLDER_PREFIX"]
session_file_name = system_setting_dict["SESSION_FILE_NAME"]
session_status_file_name = system_setting_dict["SESSION_STATUS_FILE_NAME"]
session_contents_folder = system_setting_dict["SESSION_CONTENTS_FOLDER"]
session_analytics_folder = system_setting_dict["SESSION_ANALYTICS_FOLDER"]

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
temp_move_flg = os.getenv("TEMP_MOVE_FLG")
#user_folder_path = os.getenv("USER_FOLDER")
#session_folder_prefix = os.getenv("SESSION_FOLDER_PREFIX")
#session_file_name = os.getenv("SESSION_FILE_NAME")
#session_status_file_name = os.getenv("SESSION_STATUS_FILE_NAME")
#session_contents_folder = os.getenv("SESSION_CONTENTS_FOLDER")
#session_analytics_folder = os.getenv("SESSION_ANALYTICS_FOLDER")

current_date = datetime.now()

# セッションの一覧を獲得
def get_session_list():
    session_nums = []
    for session_folder_name in os.listdir(user_folder_path):
        if session_folder_name.startswith(session_folder_prefix):
            match = re.match(rf'{session_folder_prefix}(\d+)', session_folder_name)
#            if match:
#                session_nums.append(int(match.group(1)))
            if match:
                session_num = int(match.group(1))
                session_folder_path = os.path.join(user_folder_path, session_folder_name)
                # chat_memory.json の存在確認
                file_path = os.path.join(session_folder_path, session_file_name)
                if os.path.exists(file_path):
                    session_nums.append(session_num)
    session_nums.sort()
    return session_nums

# セッションの一覧を獲得(画面用)
def get_session_list_visible():
    session_list = []
    session_nums = get_session_list()
    for session_num in session_nums:
        session_id = str(session_num)
        session_file_dict = get_session_data(session_id)
        last_update_date = get_history_update_date(session_file_dict)
        session_list.append([session_num, last_update_date])

#    for session_folder_name in os.listdir(user_folder_path):
#        if session_folder_name.startswith(session_folder_prefix):
#            match = re.match(rf'{session_folder_prefix}(\d+)', session_folder_name)
#            if match:
#                session_file_dict = get_session_data(match.group(1))
#                last_update_date = get_history_update_date(session_file_dict)
#                session_list.append([int(match.group(1)), last_update_date])

    session_list_sorted = sorted(session_list, key=lambda x: x[1], reverse=True)
    return session_list_sorted

# セッションIDを元にセッションの辞書データを取得する関数
def get_session_data(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = user_folder_path + session_key + "/" + session_file_name
    session_file_dict = dmu.read_json_file(session_file_path)
    return session_file_dict

# 辞書データから最大のキーを取得する関数
def max_seq_dict(session_dict):
    max_seq = 0
    seqs = [int(k) for k in session_dict.keys() if k.isdigit()]
    if seqs:
        max_seq = max(seqs, key=int)
    return str(max_seq)

# セッション名を取得
def get_session_name(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = user_folder_path + session_key + "/" + session_file_name
    session_file_dict = dmu.read_json_file(session_file_path)   
    session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
    session_name = ""

    # 最大シーケンス／サブシーケンスからセッション名を取得
    if session_file_active_dict:
        max_seq = max_seq_dict(session_file_active_dict)
        max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
        session_name = session_file_active_dict[max_seq][max_sub_seq]["setting"]["session_name"]

    return session_name

# 会話履歴の最終更新日を取得
def get_history_update_date(chat_history_active_dict):
    max_seq = max(chat_history_active_dict.keys(), key=int)
    max_sub_seq = 0
    last_update_date = current_date
    
    sub_seq_candidates = [k for k, v in chat_history_active_dict[max_seq].items() if isinstance(v, dict) and "digest" in v]
    if sub_seq_candidates:
        max_sub_seq = max(sub_seq_candidates, key=int)
        last_update_date = datetime.strptime(chat_history_active_dict[max_seq][max_sub_seq]["response"]["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
        
    return last_update_date

# エージェントファイルを取得
def get_agent_file(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = user_folder_path + session_key + "/" + session_file_name
    session_file_dict = dmu.read_json_file(session_file_path)   
    session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
    agent_file = ""

    # 最大シーケンス／サブシーケンスからエージェントファイルを取得
    if session_file_active_dict:
        max_seq = max_seq_dict(session_file_active_dict)
        max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
        agent_file = session_file_active_dict[max_seq][max_sub_seq]["setting"]["agent_file"]

    return agent_file

# シチュエーションを取得
def get_situation(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = user_folder_path + session_key + "/" + session_file_name
    session_file_dict = dmu.read_json_file(session_file_path)   
    session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
    situation = {}

    # 最大シーケンス／サブシーケンスからシチュエーションを取得
    if session_file_active_dict:
        max_seq = max_seq_dict(session_file_active_dict)
        max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
        situation = session_file_active_dict[max_seq][max_sub_seq]["prompt"]["query"]["situation"]

    return situation

# 新しいセッションIDを発番する
def set_new_session_id():
    new_session_num = max(get_session_list())+1 if get_session_list() else 0
    new_session_id = str(new_session_num)
    return new_session_id

# セッションクラス
class DigiMSession:
    def __init__(self, session_id="", session_name=""):
        self.session_id = session_id if session_id else set_new_session_id()
        self.session_name = session_name
        self.session_folder_path = user_folder_path + session_folder_prefix + self.session_id +"/" 
        self.session_vec_folder_path = user_folder_path + session_folder_prefix + self.session_id +"/vecs/" 
        self.session_file_path = self.session_folder_path + session_file_name
        self.session_status_path = self.session_folder_path + session_status_file_name
        self.session_contents_folder_path = self.session_folder_path + session_contents_folder
        self.session_analytics_folder_path = self.session_folder_path + session_analytics_folder
        self.set_history()

    # ヒストリーの再読込
    def set_history(self):
        self.chat_history_dict = self.get_history()
        self.chat_history_active_dict = self.get_history_active()
        self.chat_history_active_omit_dict = self.get_history_active_omit()

    # 会話履歴を指定したseqとsub_seqまでで切り取り
    def extract_history_by_keys(self, chat_history_dict, seq_str="", sub_seq_str=""):
        trimmed_dict = {}
        if seq_str:
            for key, sub_dict in chat_history_dict.items():
                if key < seq_str:
                    trimmed_dict[key] = sub_dict
                elif key == seq_str:
                    if sub_seq_str:
                        trimmed_dict[key] = {sub_key: sub_dict[sub_key] for sub_key in sub_dict if sub_key <= sub_seq_str}
                    else:
                        trimmed_dict[key] = sub_dict
            return trimmed_dict
        else:
            return chat_history_dict

    # セッションのステータスを獲得する
    def get_status(self):
        status_dict = {}
        status_dict = dmu.read_yaml_file(self.session_status_path)
        if "status" in status_dict:
            status = status_dict["status"]
        else:
            status = "UNLOCKED"
        return status

    # 全ての会話履歴を獲得する
    def get_history(self):
        chat_history_dict = {}
        chat_history_dict = dmu.read_json_file(self.session_file_path)
        return chat_history_dict
    
    # 有効な会話履歴を獲得する
    def get_history_active(self):
        chat_history_active_dict = {}
        if self.chat_history_dict:
            chat_history_active_dict = {k: v for k, v in self.chat_history_dict.items() if "SETTING" in v and v["SETTING"].get("FLG") == "Y"}
        return chat_history_active_dict

    # Sub_Seqの最大・最小の辞書型データを獲得する
    def get_history_active_omit(self):
        chat_history_active_omit_dict = {}
        if self.chat_history_active_dict:
            for key, sub_dict in self.chat_history_active_dict.items():
                sub_seqs = sorted((int(k) for k in sub_dict if k != "SETTING"))
                # 最小サブキーと最大サブキーを取得
                min_subseq = str(sub_seqs[0])
                max_subseq = str(sub_seqs[-1])
                chat_history_active_omit_dict[key] = {}
                chat_history_active_omit_dict[key]["1"] = {}
                chat_history_active_omit_dict[key]["1"]["setting"] = sub_dict[str(min_subseq)]["setting"]
                if "prompt" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["prompt"] = sub_dict[str(min_subseq)]["prompt"]
                if "image" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["image"] = sub_dict[str(max_subseq)]["image"]
                if "response" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["response"] = sub_dict[str(max_subseq)]["response"]
                if "digest" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["digest"] = sub_dict[str(max_subseq)]["digest"]
                if "log" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["log"] = sub_dict[str(max_subseq)]["log"]
                if "feedback" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["feedback"] = sub_dict[str(max_subseq)]["feedback"]
        return chat_history_active_omit_dict

    # 最新のエージェントを取得
    def get_history_max_agent(self):
        chat_history_active_dict = self.get_history_active()
        max_seq = max(chat_history_active_dict.keys(), key=int)
        max_sub_seq = 0
        agent_file = ""
        agent_name = ""
        engine_name = ""
        sub_seq_candidates = [k for k, v in chat_history_active_dict[max_seq].items() if isinstance(v, dict) and "setting" in v]
        if sub_seq_candidates:
            max_sub_seq = max(sub_seq_candidates, key=int)
            agent_file = chat_history_active_dict[max_seq][max_sub_seq]["setting"]["agent_file"]
            agent_name = chat_history_active_dict[max_seq][max_sub_seq]["setting"]["name"]
            engine_name = chat_history_active_dict[max_seq][max_sub_seq]["setting"]["engine"]["NAME"]
        return agent_name+":"+engine_name 
    
    # 最新のダイジェストを取得
    def get_history_max_digest(self):
        chat_history_active_dict = self.get_history_active()
        max_seq = max(chat_history_active_dict.keys(), key=int)
        max_sub_seq = 0
        chat_history_max_digest_dict = {}
        sub_seq_candidates = [k for k, v in chat_history_active_dict[max_seq].items() if isinstance(v, dict) and "digest" in v]
        if sub_seq_candidates:
            max_sub_seq = max(sub_seq_candidates, key=int)
            chat_history_max_digest_dict = chat_history_active_dict[max_seq][max_sub_seq]["digest"]
        return max_seq, max_sub_seq, chat_history_max_digest_dict
    
    # 会話メモリを獲得する（トークン制限で切り取り）
    def get_memory(self, query_vec, model_name, tokenizer, memory_limit_tokens, memory_role="both", memory_priority="latest", memory_similarity=False, memory_similarity_logic="cosine", memory_digest="Y", seq_limit="", sub_seq_limit=""):
        memories_list = []
        memories_list_prompt = []
        total_tokens = 0
        
        # アクティブな会話履歴からメモリに設定する履歴を取得
        chat_history_active_dict = self.extract_history_by_keys(self.chat_history_active_dict, seq_limit, sub_seq_limit)

        if chat_history_active_dict:
            # 最新のダイジェストを取得
            if memory_digest == "Y":
                max_seq, max_sub_seq, chat_history_max_digest_dict = self.get_history_max_digest()
                if chat_history_max_digest_dict:
                    # トークン制限を超えていなければ、ダイジェストを設定
                    total_tokens += chat_history_max_digest_dict["token"]
                    if total_tokens <= memory_limit_tokens:
                        chat_history_max_digest_dict["vec_text"] = []
                        similarity_prompt = 0
                        if memory_similarity:
                            chat_history_max_digest_dict["vec_text"] = self.get_vec_file(max_seq, max_sub_seq, "digest")
                            similarity_prompt = dmu.calculate_similarity_vec(query_vec, chat_history_max_digest_dict["vec_text"], memory_similarity_logic)
                        memories_list.append({"seq": max_seq, "sub_seq": max_sub_seq, "type": "digest", "role": chat_history_max_digest_dict["role"], "timestamp": chat_history_max_digest_dict["timestamp"], "token": chat_history_max_digest_dict["token"], "similarity_prompt": similarity_prompt, "text": chat_history_max_digest_dict["text"], "vec_text": chat_history_max_digest_dict["vec_text"]})
        
            # 各履歴を取得
            for k, v in chat_history_active_dict.items():
                for k2, v2 in v.items():
                    if k2 != "SETTING":
                        similarity_prompt = 0
                        v2["prompt"]["query"]["vec_text"] = []
                        v2["response"]["vec_text"] = []
                        if memory_role in ["both", "user"]:
                            if v2["prompt"]["role"] == "user":
                                if memory_similarity:
                                    v2["prompt"]["query"]["vec_text"] = self.get_vec_file(k, k2, "query")
                                    similarity_prompt = dmu.calculate_similarity_vec(query_vec, v2["prompt"]["query"]["vec_text"], memory_similarity_logic)
                                memories_list.append({"seq": k, "sub_seq": k2, "type": v2["prompt"]["role"], "role": v2["prompt"]["role"], "timestamp": v2["prompt"]["timestamp"], "token": v2["prompt"]["query"]["token"], "similarity_prompt": similarity_prompt, "text": v2["prompt"]["query"]["text"], "vec_text": v2["prompt"]["query"]["vec_text"]})
                        if memory_role in ["both", "assistant"]:
                            if v2["prompt"]["role"] == "assistant":
                                if memory_similarity:
                                    v2["response"]["vec_text"] = self.get_vec_file(k, k2, "response")
                                    similarity_prompt = dmu.calculate_similarity_vec(query_vec, v2["response"]["vec_text"], memory_similarity_logic)
                                memories_list.append({"seq": k, "sub_seq": k2, "type": v2["response"]["role"], "role": v2["response"]["role"], "timestamp": v2["response"]["timestamp"], "token": v2["response"]["token"], "similarity_prompt": similarity_prompt, "text": v2["response"]["text"], "vec_text": v2["response"]["vec_text"]})

            # 各履歴をプライオリティ順に並び替え
            if memory_priority == "latest":
                memories_list_priority = sorted(memories_list, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"), reverse=True)
            elif memory_priority == "oldest":
                memories_list_priority = sorted(memories_list, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"))
            elif memory_similarity and memory_priority == "similar":
                memories_list_priority = sorted(memories_list, key=lambda x: x["similarity_prompt"])
            else :
                memories_list_priority = memories_list
            
            # トークン制限を超えないように会話メモリを設定
            memories_list_selected = []
            for memory_list_priority in memories_list_priority:
                total_tokens += memory_list_priority["token"]
                if total_tokens <= memory_limit_tokens:
                    memories_list_selected.append(memory_list_priority)

            # 最後にタイムスタンプでソート
            memories_list_prompt = sorted(memories_list_selected, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"))
        
        return memories_list_prompt

    # ベクトルデータをセッションフォルダに保存する
    def save_vec_file(self, seq, sub_seq="1", mode="query", vec_text=[]):
        # セッションフォルダがなければ作成
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)
        
        # ベクトルデータの保存フォルダがなければ作成
        if not os.path.exists(self.session_vec_folder_path):
            os.makedirs(self.session_vec_folder_path, exist_ok=True)
        
        # ベクトルデータを.npy形式で保存
        vec_file_name = seq+"-"+sub_seq+"_"+mode+".npy"
        dmu.save_vectext_to_npy(vec_text, self.session_vec_folder_path+vec_file_name)

        return vec_file_name

    # ベクトルデータをセッションフォルダから読み込む
    def get_vec_file(self, seq, sub_seq="1", mode="query"):
        vec_file_name = seq+"-"+sub_seq+"_"+mode+".npy"
        vec_text=[]
        vec_text = dmu.read_vectext_to_npy(self.session_vec_folder_path+vec_file_name)
        return vec_text

    # セッションのステータスを保存する
    def save_status(self, status):
        status_dict = {"status": status}
        
        # セッションフォルダがなければ作成
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)
        
        # セッションステータスをYAML形式で保存
        with open(self.session_status_path, 'w', encoding='utf-8') as f:
            dmu.save_yaml_file(status_dict, self.session_status_path)

    # 会話履歴を保存する
    def save_history(self, seq, chat_dict_key, chat_dict, level="SEQ", sub_seq="1"):
        chat_history_dict = {}
        
        # セッションフォルダがなければ作成
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)

        # 保存済みの会話履歴を取得
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(self.session_file_path)

        # 会話履歴にseqがなければFLGと一緒に設定
        if seq not in chat_history_dict:
            chat_history_dict[seq] = {}
            chat_history_dict[seq]["SETTING"] = {}
            chat_history_dict[seq]["SETTING"]["FLG"] = "Y"
        
        # 会話履歴にデータを追加
        if level == "SEQ":
            chat_history_dict[seq]["SETTING"][chat_dict_key] = chat_dict
        elif level == "SUB_SEQ":
            if sub_seq not in chat_history_dict[seq]:
                chat_history_dict[seq][sub_seq] = {}
            chat_history_dict[seq][sub_seq][chat_dict_key] = chat_dict

        # 会話履歴を保存
        with open(self.session_file_path, 'w', encoding='utf-8') as f:
            json.dump(chat_history_dict, f, ensure_ascii=False, indent=4)

    # 会話履歴のシーケンスを取得する
    def get_seq_history(self):
        seq = 0
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            seq = max(int(key) for key in chat_history_dict.keys())
        return seq
    
    # 会話履歴のシーケンスのステータスを変更する
    def chg_seq_history(self, seq, value="N"):
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict[seq]["SETTING"]["FLG"] = value
        with open(self.session_file_path, 'w', encoding='utf-8') as f:
            json.dump(chat_history_dict, f, ensure_ascii=False, indent=4)

    # 会話履歴にフィードバックを保存する
    def set_feedback_history(self, seq, sub_seq, feedbacks={}):
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict[seq][sub_seq]["feedback"] = feedbacks
        with open(self.session_file_path, 'w', encoding='utf-8') as f:
            json.dump(chat_history_dict, f, ensure_ascii=False, indent=4)

    # 会話履歴に分析結果を保存する
    def set_analytics_history(self, seq, sub_seq, analytics={}):
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict[seq][sub_seq]["analytics"] = analytics
        with open(self.session_file_path, 'w', encoding='utf-8') as f:
            json.dump(chat_history_dict, f, ensure_ascii=False, indent=4)

    # 会話履歴の詳細情報を取得する
    def get_detail_info(self, seq, sub_seq="1"):
        chat_detail_info = ""
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict_seq = chat_history_dict[seq][sub_seq]

            chat_detail_info += "\n【実行情報】\n"
            chat_detail_info += "実行関数："+chat_history_dict_seq["setting"]["engine"]["FUNC_NAME"]+"\n"
            chat_detail_info += "プロンプトテンプレート："+chat_history_dict_seq["prompt"]["prompt_template"]["setting"]+"\n"
            chat_detail_info += "RAGデータ："
            for rag_set_dict in chat_history_dict_seq["prompt"]["knowledge_rag"]["setting"]:
                chat_detail_info += str(rag_set_dict["DATA"])
            chat_detail_info += "\n"

            chat_detail_info += "\n【実行結果】\n"
            chat_detail_info += "エージェント："+chat_history_dict_seq["setting"]["agent_file"]+"\n"
            chat_detail_info += "実行モデル："+chat_history_dict_seq["setting"]["engine"]["MODEL"]+"("+str(chat_history_dict_seq["setting"]["engine"]["PARAMETER"])+")\n"
            chat_detail_info += "回答時間："+dmu.get_time_diff(chat_history_dict_seq["prompt"]["timestamp"], chat_history_dict_seq["response"]["timestamp"], format_str="%Y-%m-%d %H:%M:%S.%f")+"\n"
            chat_detail_info += "入力トークン数："+str(chat_history_dict_seq["prompt"]["token"])+"\n"
            chat_detail_info += "出力トークン数："+str(chat_history_dict_seq["response"]["token"])+"\n"

            if "log" in chat_history_dict_seq:
                chat_detail_info += "\n【実行履歴】\n"
                chat_detail_info += chat_history_dict_seq["log"]["timestamp_log"]
                
            if "digest" in chat_history_dict_seq:
                chat_detail_info += "\n【会話のダイジェスト】\n"
                chat_detail_info += "エージェント："+chat_history_dict_seq["digest"]["agent_file"]+"\n"
                if "model" in chat_history_dict_seq["digest"]:
                    chat_detail_info += "実行モデル："+chat_history_dict_seq["digest"]["model"]+"\n"
                chat_detail_info += "出力トークン数："+str(chat_history_dict_seq["digest"]["token"])+"\n"
                chat_detail_info += chat_history_dict_seq["digest"]["text"]+"\n"

            chat_detail_info += "\n【メモリ】\n"
            for memory_set_dict in chat_history_dict_seq["response"]["reference"]["memory"]:
                chat_detail_info += memory_set_dict["log"]

            chat_detail_info += "\n【RAG検索用クエリ】\n"
            if chat_history_dict_seq["prompt"]["RAG_query_genetor"]:
                chat_detail_info += "エージェント："+chat_history_dict_seq["prompt"]["RAG_query_genetor"]["agent_file"]+"\n"
                chat_detail_info += "実行モデル："+chat_history_dict_seq["prompt"]["RAG_query_genetor"]["model"]+"\n"
                chat_detail_info += "入力トークン数："+str(chat_history_dict_seq["prompt"]["RAG_query_genetor"]["prompt_token"])+"\n"
                chat_detail_info += "出力トークン数："+str(chat_history_dict_seq["prompt"]["RAG_query_genetor"]["response_token"])+"\n"          
                chat_detail_info += chat_history_dict_seq["prompt"]["RAG_query_genetor"]["llm_response"]+"\n"

            chat_detail_info += "\n【メタ検索】\n"
            if chat_history_dict_seq["prompt"]["meta_search"]:
                chat_detail_info += "[日付検索]\n"
                chat_detail_info += "エージェント："+chat_history_dict_seq["prompt"]["meta_search"]["date"]["agent_file"]+"\n"
                chat_detail_info += "実行モデル："+chat_history_dict_seq["prompt"]["meta_search"]["date"]["model"]+"\n"
                chat_detail_info += "入力トークン数："+str(chat_history_dict_seq["prompt"]["meta_search"]["date"]["prompt_token"])+"\n"
                chat_detail_info += "出力トークン数："+str(chat_history_dict_seq["prompt"]["meta_search"]["date"]["response_token"])+"\n"          
                chat_detail_info += "検索条件："+str(chat_history_dict_seq["prompt"]["meta_search"]["date"]["condition_list"])+"\n"
                chat_detail_info += chat_history_dict_seq["prompt"]["meta_search"]["date"]["llm_response"]+"\n"
            
            chat_detail_info += "\n【RAGコンテキスト】\n["
            for rag_set_dict in chat_history_dict_seq["response"]["reference"]["knowledge_rag"]:
                chat_detail_info += "{"+ rag_set_dict.replace("\n", "").replace("$", "＄") + "},\n"
            if chat_detail_info.endswith(",\n"):
                chat_detail_info = chat_detail_info[:-2] + "]"+"\n"

            chat_detail_info += "\n【コンテンツコンテキスト】\n"
            for content_dict in chat_history_dict_seq["prompt"]["query"]["contents"]:
                chat_detail_info += content_dict["context"]+"\n"
                
        return chat_detail_info

    # コンテンツファイルを保存する
    def save_contents_file(self, from_file_path, content_file_name):
        to_folder_path = self.session_contents_folder_path
        to_file_path = to_folder_path + content_file_name
        # コンテンツフォルダがなければ作成
        if not os.path.exists(to_folder_path):
            os.makedirs(to_folder_path, exist_ok=True)
        if temp_move_flg == "Y":
            dmu.copy_file(from_file_path, to_file_path)
